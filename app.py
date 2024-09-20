import boto3
import hashlib
import io
import logging
import os
import pyotp
import streamlit as st

from botocore.client import Config
from PIL import Image, ImageOps


logger = logging.getLogger(st.__name__)

TOTP_KEY = os.environ.get('TOTP_SECRET_KEY')
ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID')
ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
CDN_BASE_URL = os.environ.get('CDN_BASE_URL')

s3_client = boto3.client('s3',
    endpoint_url=f'https://{ACCOUNT_ID}.r2.cloudflarestorage.com',
    aws_access_key_id=ACCESS_KEY_ID,
    aws_secret_access_key=SECRET_ACCESS_KEY,
    config=Config(signature_version='s3v4')
)

ROTATE_DEGREES = {
    '0° :arrow_heading_up:': '0',
    '90° :arrow_right_hook:': '90',
    '180° :arrow_heading_down:': '180',
    '270° :leftwards_arrow_with_hook:': '270',
}

def set_page_config():
    page_config = {
        'page_title': 'Image Processor',
        'layout': 'wide'
    }
    st.set_page_config(**page_config)

# Set page config
def set_page_config():
    page_config = {
        'page_title': 'File Scanner',
        'layout': 'wide'
    }
    st.set_page_config(**page_config)

# Callback for login button
def on_login_click(code: str, username: str):
    if verify_code(code):
        st.session_state.authenticated_user = username.title()

# Verfiy totp code
def verify_code(code: str) -> bool:
    totp = pyotp.TOTP(TOTP_KEY)
    return totp.verify(code, valid_window=3)

# Callback for logout button
def on_logout_click():
    st.session_state.authenticated_user = None

def get_size_format(b, factor=1024, suffix='B'):
    for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if b < factor:
            return f'{b:.2f}{unit}{suffix}'
        b /= factor
    return f'{b:.2f}Y{suffix}'

def main():
    set_page_config()
    container_info = st.container(border=True)

    container_info.title('Process Images and Upload to CDN')
    container_info.markdown('''
                This tool can perform the following actions.
                - Compress the images and convert them to `.webp` format.
                - Upload the compressed image to CDN.
            ''')

    login_form_placeholder = st.empty()
    if st.session_state.setdefault('authenticated_user', None) is None:
        login_container = login_form_placeholder.container(border=True)
        username = login_container.text_input('Username', type='default')
        code = login_container.text_input('OTP', type='default')
        login_button = login_container.button(
            label='Login',
            on_click=on_login_click,
            kwargs={'code': code, 'username': username},
        )
        if login_button:
            if not verify_code(code=code):
                st.error('Invalid OTP. Access denied.')
                st.stop()
    else:
        login_form_placeholder.empty()
        st.success(f'Welcome, {st.session_state.authenticated_user}!')
        logout_button = st.button(label='Logout', on_click=on_logout_click)

        file_config = {
            'label': 'Upload your files :page_facing_up:',
            'type': None, # Accept all types of files.
            'accept_multiple_files': True,
            'help': 'Some help for file upload'
        }
        uploaded_files = st.file_uploader(**file_config)

        st.divider()

        if uploaded_files is not None:
            tab_labels = [file.name for file in uploaded_files]
            if tab_labels:
                for tab in st.tabs(tab_labels):
                    with tab:
                        image_file = uploaded_files[tab._cursor.parent_path[1]]
                        logger.info(f'Uploaded File: {image_file}')
                        try:
                            image = Image.open(image_file)
                            if image.mode != 'RGB':
                                image.convert('RGB')
                            # If an image has an EXIF Orientation tag, other than 1, transpose the image accordingly, and remove the orientation data.
                            ImageOps.exif_transpose(image, in_place=True)
                        except Exception as e:
                            msg = f'Error opening image file. Error: {e}'
                            logger.debug(msg=msg)
                            st.stop()
                        width, height = image.size
                        bytes_data = image_file.getvalue()
                        sum_md5 = hashlib.md5(bytes_data).hexdigest() # For component keys
                        container_processing = st.container(border=True)
                        col1, col2, col3, col4 = container_processing.columns(4)
                        with col1:
                            col1_original_image_container = st.container(border=True)
                            col1_original_image_container.image(
                                image,
                                caption=f'Original Image ({get_size_format(image_file.size)})', use_column_width=True)
                        with col2:
                            # Image Size Reduction
                            col2_reduce_size_container = st.container(border=True)
                            reduce_size = col2_reduce_size_container.selectbox(
                                label='Reduce Size',
                                options=[
                                    f'{int(width)}x{int(height)}',
                                    f'{int(width/2)}x{int(height/2)}',
                                    f'{int(width/4)}x{int(height/4)}',
                                ],
                                key=f'reduce_size_selectbox_{sum_md5}'
                            )
                            reduced_width, reduced_height = reduce_size.split('x')
                            reduced_image = image.resize((int(reduced_width), int(reduced_height)))
                            # Image Rotation
                            col2_rotation_container = st.container(border=True)
                            rotate_toggle = col2_rotation_container.toggle(
                                label='Rotate Image',
                                key=f'rotate_toggle_{sum_md5}',
                            )
                            if rotate_toggle:
                                rotation_degrees = col2_rotation_container.radio (
                                    label='Rotate Image (Counter Clockwise :arrows_counterclockwise:)',
                                    options=ROTATE_DEGREES.keys(),
                                    key=f'rotation_degrees_radio_{sum_md5}',
                                )                       
                                rotated_image = reduced_image.rotate(angle=float(ROTATE_DEGREES.get(rotation_degrees)))
                            else:
                                rotated_image = reduced_image
                            col2_crop_container = st.container(border=True)
                            crop_toggle = col2_crop_container.toggle(
                                label='Crop Image',
                                key=f'crop_toggle_{sum_md5}',
                            )
                            if crop_toggle:
                                left, right = col2_crop_container.select_slider(
                                    label='Left - Right',
                                    options=[i for i in range(width+1)],
                                    value=(0, width)
                                )
                                top, bottom = col2_crop_container.select_slider(
                                    label='Top - Bottom',
                                    options=[i for i in range(height+1)],
                                    value=(0, height)
                                )
                                cropped_image = rotated_image.crop((left, top, right, bottom))
                            else:
                                cropped_image = rotated_image
                            # Image quality
                            col2_quality_container = st.container(border=True)
                            col2_img_quality_slider = col2_quality_container.slider(
                                label='Image Quality :star-struck:',
                                min_value=0,
                                max_value=100,
                                value=50,
                                step=10,
                                key=f'image_quality_slider_{sum_md5}',
                                args=[sum_md5],
                            )
                            file_name, _ = os.path.splitext(image_file.name)
                            compressed_image_name = f'{file_name}_compressed.webp'
                            compressed_image_buffer = io.BytesIO()
                            cropped_image.save(
                                compressed_image_buffer,
                                format='webp',
                                quality=col2_img_quality_slider,
                                optimize=True
                                )
                        with col3:
                            col3_container = st.container(border=True)
                            col3_container.image(
                                compressed_image_buffer,
                                caption=f'Modified Image ({get_size_format(compressed_image_buffer.getbuffer().nbytes)})',
                                use_column_width=True)
                        with col4:
                            col4.download_button(
                                label='Download',
                                data=compressed_image_buffer,
                                file_name=compressed_image_name,
                                mime='image/webp')
                            button_upload_file = col4.button(label='Upload to CDN', key=f'upload_{sum_md5}')
                            if button_upload_file:
                                st.toast(f'Uploading file to CDN "{compressed_image_name}"')
                                try:
                                    response = s3_client.put_object(
                                        Bucket=BUCKET_NAME,
                                        Key=f'images/{compressed_image_name}',
                                        Body=compressed_image_buffer.getvalue()
                                    )
                                    if response.get('ResponseMetadata').get('HTTPStatusCode') == 200:
                                        st.success(f'Successfuly uploaded image to CDN.')
                                        uploaded_image_url = f'''{CDN_BASE_URL}/images/{compressed_image_name}'''
                                        st.code(uploaded_image_url, language='python')
                                except Exception as e:
                                    msg = f'Error occurred while uploading image to CDN. Error {e}'
                                    logger.debug(msg)
                                    st.error(msg)

if __name__ == '__main__':
    main()
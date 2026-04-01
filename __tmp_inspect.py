import inspect 
import reflex as rx 
print('upload_files:', rx.upload_files) 
print('signature:', inspect.signature(rx.upload_files)) 
print('annotations:', getattr(rx.upload_files, '__annotations__', {})) 

import os
from setuptools import Extension, setup

sanitize = os.environ.get("STAQTAPP_TDS_SANITIZE", "").strip().lower()
extra_compile_args = ["-O3"]
extra_link_args = []
if sanitize:
    mapping = {
        "address": ["-fsanitize=address", "-fno-omit-frame-pointer"],
        "undefined": ["-fsanitize=undefined"],
        "thread": ["-fsanitize=thread"],
        "all": ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
    }
    flags = mapping.get(sanitize, sanitize.split())
    extra_compile_args.extend(flags)
    extra_link_args.extend([f for f in flags if f.startswith("-fsanitize")])

setup(
    ext_modules=[
        Extension(
            "staqtapp_tds._native_index",
            ["src/staqtapp_tds/_native_index.c"],
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
        ),
        Extension(
            "staqtapp_tds._csv_scan_kernel",
            ["src/staqtapp_tds/_csv_scan_kernel.c"],
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
        )
    ]
)

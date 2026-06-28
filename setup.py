from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            "staqtapp_tds._native_index",
            sources=["src/staqtapp_tds/_native_index.c"],
            extra_compile_args=["-O3"],
        )
    ]
)

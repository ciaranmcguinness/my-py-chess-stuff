load("//:pyoxidizer_common.bzl", "python_distribution")

def make(ctx):
    # Create a default Python distribution and an executable from the
    # `random_move` module. Adjust python_version or additional files as needed.
    dist = ctx.default_python_distribution()

    exe = ctx.binary("random_move")
    exe.set_main_module("random_move")

    return [dist, exe]

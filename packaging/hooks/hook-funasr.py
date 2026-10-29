# FunASR registers models with torch.jit.script at import time; TorchScript reads
# the original .py files, so the package source must ship alongside the PYZ.
module_collection_mode = {"funasr": "pyz+py"}

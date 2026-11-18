"""The MSHvSF (Marvel Super Heroes vs. Street Fighter, USA, SLUS-00793) disc builder: the counterpart of builder/xvb.

pipeline.py   the build: verify, extract, sprite tiers, sound levels, arcade frames, disc (tools/tagload/mktag.py and
              tools/ap8/mkap8.py run unmodified inside a harness, our MIPS code from builder/data/mshvsf/blobs)
web.py        the browser side (patcher/src/worker.js)
sprites.py    the sprite tier encoders (DSM1 / DSH1 ports onto batched kernels: kernels.py, dsm1.py, dsh1.py)
"""

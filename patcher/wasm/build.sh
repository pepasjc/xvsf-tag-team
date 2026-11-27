#!/bin/sh
# the ADPCM encoder for the page (patcher/make.py embeds adpcm.wasm): Rust, target wasm32-unknown-unknown
cd "$(dirname "$0")/adpcm" && RUSTFLAGS="-C target-feature=+simd128" cargo build --release --target wasm32-unknown-unknown && cp target/wasm32-unknown-unknown/release/adpcm.wasm ../adpcm.wasm

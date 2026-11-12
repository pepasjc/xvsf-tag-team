/* Loader for the vendored zopfli (patcher/vendor/zopfli: the WebAssembly build of Google's zopfli from the
 * npm package @gfx/zopfli 1.0.15, Apache-2.0).  Only the 8 MB build uses it: tools/mkap8disc.py packs each
 * character block with zopfli, and the same library gives the same bytes here as on the command line.
 *
 *   loadZopfli(glueSource, wasmBase64) -> Promise of deflate(Uint8Array, iterations) -> Uint8Array (raw deflate)
 *
 * glueSource is the package's Emscripten glue (a CommonJS module); it is run with a three-line `require`.
 */
"use strict";
function loadZopfli(glueSource, wasmBase64) {
  return new Promise((resolve, reject) => {
    try {
      const b64 = { toByteArray: (s) => { const bin = atob(s), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; } };
      const mod = { exports: {} };
      const req = (name) => {
        if (name === "base64-js") return b64;
        if (name === "./libzopfli-wasm") return wasmBase64;
        throw new Error("zopfli glue asked for module " + name);
      };
      // the glue exports its Module object only when it detects Node; hand it out in every environment
      new Function("require", "module", "exports", "__dirname", glueSource + "\n;module.exports = Module;")(req, mod, mod.exports, "");
      const z = mod.exports;
      const deflate = (input, iterations) => {
        const inPtr = z.allocate(input, "i8", z.ALLOC_NORMAL);
        const out = z._createZopfliJsOutput();
        // (in, size, out, format 2 = raw deflate, verbose, verbose_more, numiterations, blocksplitting, blocksplittingmax)
        z._compress(inPtr, input.length, out, 2, 0, 0, iterations, 1, 15);
        const p = z._getBuffer(out), n = z._getBufferSize(out);
        const result = z.HEAPU8.slice(p, p + n);
        z._deallocate(p); z._deallocate(out); z._deallocate(inPtr);
        return result;
      };
      if (z.calledRun) resolve(deflate); else z.onRuntimeInitialized = () => resolve(deflate);
    } catch (e) { reject(e); }
  });
}
if (typeof module !== "undefined") module.exports = loadZopfli;

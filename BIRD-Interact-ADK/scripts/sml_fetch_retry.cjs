// E-23 workaround: the deploy POST reuses a keep-alive socket the API closed while sml-cli compiled; retry once on a fresh socket.
const orig = globalThis.fetch;
globalThis.fetch = async (...args) => {
  try { return await orig(...args); }
  catch (e) {
    const msg = String((e && e.cause && e.cause.message) || e);
    if (/other side closed|socket hang up|ECONNRESET/i.test(msg)) { process.stderr.write('[fetch_retry] retrying after: ' + msg + '\n'); return await orig(...args); }
    throw e;
  }
};

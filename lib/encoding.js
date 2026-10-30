const {isUtf8} = require('node:buffer');
// Python's original surrogateescape convention is useful for raw Unix names.
// JS callers normally receive a Buffer when the bytes are not valid UTF-8.
function encodeBytes(value) {
  const parts = [];
  for (const char of value) {
    const code = char.charCodeAt(0);
    parts.push(code >= 0xdc80 && code <= 0xdcff ? Buffer.from([code-0xdc00]) : Buffer.from(char));
  }
  return Buffer.concat(parts);
}
function decodeBytes(raw) {
  let value = '';
  for (let i = 0; i < raw.length;) {
    const byte = raw[i];
    const length = byte < 0x80 ? 1 : byte >= 0xc2 && byte <= 0xdf ? 2 : byte >= 0xe0 && byte <= 0xef ? 3 : byte >= 0xf0 && byte <= 0xf4 ? 4 : 0;
    const candidate = raw.subarray(i,i+length);
    if (length && candidate.length === length && isUtf8(candidate)) { value += candidate.toString(); i += length; }
    else { value += String.fromCharCode(0xdc00+byte); i++; }
  }
  return value;
}
module.exports = {encodeBytes,decodeBytes};

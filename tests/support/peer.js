const { EventEmitter } = require('node:events');
const { Connection, NAMESPACE } = require('../../lib/dbgp');
const { Session } = require('../../lib/session');

function frame(xml, terminator = 0) {
  const body = Buffer.from(xml);
  return Buffer.concat([Buffer.from(`${body.length}\0`), body, Buffer.from([terminator])]);
}
function response(request, attributes = '', payload = '') {
  return `<response xmlns="${NAMESPACE}" command="${request.name}" transaction_id="${request.id}" ${attributes}>${payload}</response>`;
}
function parseCommand(packet) {
  const text = packet.toString().replace(/\0$/, '');
  const argumentsText = text.split(' -- ')[0];
  const args = {};
  for (const match of argumentsText.matchAll(/-([A-Za-z]) ("(?:\\.|[^"\\])*"|[^\s]+)/g)) {
    args[match[1]] = match[2].startsWith('"')
      ? match[2].slice(1,-1).replace(/\\([\\"])/g,'$1').replace(/\\0/g,'\0') : match[2];
  }
  return {name:text.split(' ')[0], id:args.i, args,
    data:text.includes(' -- ') ? Buffer.from(text.split(' -- ')[1], 'base64') : undefined, packet};
}
class Socket extends EventEmitter {
  commands = [];
  destroyed = false;
  write(packet, callback) {
    const request = parseCommand(packet);
    this.commands.push(request);
    this.emit('command',request);
    callback?.();
  }
  destroy() { if (!this.destroyed) { this.destroyed = true; this.emit('close'); } }
  reply(index,attributes = '',payload = '') {
    this.emit('data',frame(response(this.commands[index],attributes,payload)));
  }
}
function harness(t, options = {}) {
  const socket = new Socket();
  const connection = new Connection(socket, options.connection);
  const session = new Session(connection, {language:'PHP'}, options.session);
  t.after(() => connection.close());
  return {socket,connection,session};
}
function property(value,{name = '$x',type = 'string',...attrs} = {}) {
  const attributes = Object.entries(attrs).map(([key,value]) => `${key}="${value}"`).join(' ');
  return `<property name="${name}" fullname="${name}" type="${type}" encoding="base64" ${attributes}>${Buffer.from(value).toString('base64')}</property>`;
}
module.exports = {frame,response,parseCommand,Socket,harness,property};

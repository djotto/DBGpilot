import {EventEmitter} from 'node:events';
import type {BrowserContext,Page,Response} from 'playwright';

export type JSONValue = null | boolean | number | string | JSONValue[] | {[key:string]:JSONValue};
export type PHPInput = null | boolean | number | bigint | string | Buffer | PHPInput[] | {[key:string]:PHPInput};
export type PHPValue = PHPInput | undefined | PartialValue;
export interface WaitOptions {timeout?:number; signal?:AbortSignal}
export interface PathMapping {local:string;remote:string;remoteCaseSensitive?:boolean}
export interface Location {fileUri?:string;file?:string;localFile?:string;pathMappingError?:string;line?:number}
export interface ExecutionResult extends Location {
  status:string;reason?:string;message?:unknown;exception?:string;breakpoint?:Breakpoint;
  responseReceived?:boolean;releaseError?:string;
}
export interface Feature {supported:boolean;value:string;enabled:boolean}
export interface Breakpoint extends Location {
  id:string;type:string;state:string;resolved?:string;hitCount?:number;hitValue?:number;hitCondition?:string;
  expression?:string|Buffer;function?:string;exception?:string;temporary?:boolean;attributes?:Record<string,unknown>;
}
export interface BreakpointOptions {
  kind?:'line'|'conditional'|'call'|'return'|'exception'|'watch';
  condition?:string|Buffer;temporary?:boolean;state?:'enabled'|'disabled';
  hitValue?:number;hitCondition?:'>='|'=='|'%';function?:string;exception?:string;
}
export interface BreakpointSpec extends BreakpointOptions {file?:string;line?:number}
export interface Frame extends Location {level:number;where?:string;type?:string;commandBegin?:string;commandEnd?:string;inputs:Frame[];attributes:Record<string,unknown>}
export interface Property {
  name:string|Buffer;fullname:string|Buffer;type:string;commonType:string;classname?:string|Buffer;
  value:PHPValue;rawValue?:Buffer;children:Property[];totalChildren:number;size?:number;
  page:number;pageSize?:number;hasChildren:boolean;childrenTruncated:boolean;valueTruncated:boolean;
  facet?:string;facets:string[];constant?:boolean;key?:string;address?:string;
}
export interface PropertyOptions {frame?:number;context?:number;depth?:number}
export interface PropertyTarget {frame?:number;context?:number;page?:number;maxData?:number;key?:string;address?:string}
export interface PropertyValueInfo {data:Buffer;size:number;truncated:boolean;page?:number;key?:string;address?:string}
export interface Snapshot {
  sessionId:number;execution:Record<string,JSONValue>;frames:Record<string,JSONValue>[];
  variables:Record<string,{value:JSONValue;[key:string]:JSONValue}>;
  expressions:Record<string,{value:JSONValue;[key:string]:JSONValue}>;
}
export interface SnapshotOptions extends PropertyOptions {variables?:string[];expressions?:string[]}
export interface SessionOptions {
  step?:<T>(title:string,body:()=>Promise<T>|T)=>Promise<T>|T;
  maxPages?:number;maxDepth?:number;maxEvents?:number;pathMappings?:PathMapping[]|PathMapper;baseDir?:string;
}
export type CommandArguments = Record<string,string|number|bigint|boolean|Buffer|null|undefined>;
export type DebuggerEvent = {type:'stopped';data:ExecutionResult}
  | {type:'stream';data:{stream:string;data:Buffer}}
  | {type:'notification';data:Record<string,unknown>}
  | {type:'closed';error:{name:string;message:string}};
export class ProtocolError extends Error {}
export class ConnectionClosed extends Error {cleanEOF:boolean;constructor(message?:string,options?:{cleanEOF?:boolean})}
export class CommandTimeout extends Error {command:string;constructor(command:string,timeout:number)}
export class XdebugError extends Error {
  command:string;code:number;attributes?:Record<string,unknown>;xml?:string;response?:Record<string,unknown>;
  constructor(command:string,code:string|number,message:string,metadata?:{attributes?:Record<string,unknown>;xml?:string;response?:Record<string,unknown>});
}
export class PathMappingError extends Error {path:string;direction:string;reason:string;constructor(path:string,direction:string,reason:string)}
export class PathMapper {
  constructor(mappings?:PathMapping[],options?:{baseDir?:string});
  readonly mappings:PathMapping[];readonly baseDir:string;
  toRemote(path:string):string;toLocal(uri:string):string;
  location(uri?:string):{localFile?:string;pathMappingError?:string};
  withOverrides(mappings:PathMapping[],options?:{baseDir?:string}):PathMapper;
}
export class Session extends EventEmitter {
  private constructor();
  readonly id:number;readonly init:Record<string,unknown>;readonly info:Record<string,unknown>;
  readonly paths:PathMapper;readonly label:string;readonly state:string;readonly lastResult:ExecutionResult;
  readonly knownBreakpoints:Record<string,Breakpoint>;
  setBreakpoint(file?:string,line?:number,options?:BreakpointOptions):Promise<string>;
  setExceptionBreakpoint(exception?:string):Promise<string>;
  getBreakpoint(id:string):Promise<Breakpoint>;breakpoints():Promise<Breakpoint[]>;
  updateBreakpoint(id:string,options?:Pick<BreakpointOptions,'state'|'hitValue'|'hitCondition'>&{line?:number}):Promise<void>;
  removeBreakpoint(id:string):Promise<unknown>;
  run(options?:WaitOptions):Promise<ExecutionResult>;runUntilBreak(options?:WaitOptions):Promise<ExecutionResult>;
  stepInto(options?:WaitOptions):Promise<ExecutionResult>;stepOver(options?:WaitOptions):Promise<ExecutionResult>;stepOut(options?:WaitOptions):Promise<ExecutionResult>;
  waitForPause(options?:WaitOptions):Promise<ExecutionResult>;nextEvent(options?:WaitOptions):Promise<DebuggerEvent>;
  detach():Promise<ExecutionResult>;stop():Promise<ExecutionResult>;release():Promise<ExecutionResult>;
  stack(options?:{frame?:number}):Promise<Frame[]>;stackDepth():Promise<number>;
  contexts(options?:{frame?:number}):Promise<Record<number,string>>;
  locals(options?:{frame?:number;context?:number}):Promise<Record<string,PHPValue>>;
  getVariable(name:string|Buffer,options?:PropertyOptions):Promise<PHPValue>;
  getProperty(name:string|Buffer,options?:PropertyOptions):Promise<Property>;
  getPropertyPage(name:string|Buffer,options?:PropertyTarget):Promise<Property>;
  propertyValue(name:string|Buffer,options?:PropertyTarget):Promise<Buffer>;
  propertyValueInfo(name:string|Buffer,options?:PropertyTarget):Promise<PropertyValueInfo>;
  evaluate(expression:string|Buffer,options?:WaitOptions&{frame?:number;page?:number}):Promise<PHPValue>;
  setVariable(name:string|Buffer,value:PHPInput,options?:{frame?:number;context?:number}):Promise<void>;
  setProperty(name:string|Buffer,expression:string|Buffer,options?:{frame?:number;context?:number;type?:string;address?:string}):Promise<boolean>;
  snapshot(options?:SnapshotOptions):Promise<Snapshot>;
  featureGet(name:string):Promise<Feature>;featureSet(name:string,value:string|number|boolean):Promise<boolean>;
  getCapabilities():Promise<Record<string,Feature>>;
  typeMap():Promise<{name:string;type:string;schemaType:string;attributes:Record<string,unknown>}[]>;
  status():Promise<ExecutionResult>;source(file?:string,options?:{begin?:number;end?:number}):Promise<Buffer>;
  setOutput(stream?:'stdout'|'stderr',mode?:0|1|2):Promise<boolean>;
  command(name:string,args?:CommandArguments,data?:string|Buffer,timeout?:number):Promise<Record<string,unknown>>;
}
export interface CaptureOptions {
  urlPattern:string|RegExp|((url:URL)=>boolean);method?:string;breakpoints?:BreakpointSpec[];
  variables?:string[];expressions?:string[];timeout?:number;signal?:AbortSignal;ideKey?:string;
}
export class PausedBrowser<T = unknown> {
  private constructor();
  readonly session:Session;readonly snapshot:Snapshot;readonly action:Promise<T>;
  finished(options?:WaitOptions):Promise<T>;close():Promise<void>;
}
export class Xdebug {
  constructor(context:BrowserContext|undefined,ideKey:string,unclaimedTimeout?:number,options?:SessionOptions&{listener?:Listener});
  readonly ideKey:string;readonly disposed:boolean;readonly captures:ReadonlySet<PausedBrowser>;
  readonly listener?:Listener;
  enableFor(url:string):Promise<void>;
  waitForSession(options?:{url?:string|RegExp;method?:string;timeout?:number;signal?:AbortSignal}):Promise<Session>;
  capture<T>(page:Page,action:()=>Promise<T>,options:CaptureOptions):Promise<PausedBrowser<T>>;
  goto(page:Page,url:string,options?:Omit<CaptureOptions,'urlPattern'>&{navigationTimeout?:number}):Promise<PausedBrowser<Response|null>>;
  dispose():Promise<void>;
}
export class Listener extends EventEmitter {
  constructor(options?:{handshakeTimeout?:number;maxSessions?:number;connectionOptions?:{maxPacketSize?:number;maxPendingCommands?:number}});
  readonly port:number;readonly host:string;readonly owners:Map<string,Xdebug>;
  readonly diagnostics:{name:string;message:string;code?:string}[];
  listen(port?:number,host?:string):Promise<this>;close():Promise<void>;
  register(owner:Xdebug):Xdebug;unregister(owner:Xdebug):void;
}
export class PartialValue {readonly type:string;readonly classname?:string|Buffer;readonly totalChildren:number;readonly children:{name:string|Buffer;value:PHPValue}[];readonly truncated:boolean;readonly rawValue?:Buffer}
export function toJSONSafe(value:unknown):JSONValue;

import {access,readFile} from 'node:fs/promises';
import path from 'node:path';

export function failure(code,message){return Object.assign(new Error(message),{code});}
export const capabilities={explicitModel:true,exactSession:true,readOnlyTools:true,workspaceWriteTools:true,hardTimeout:true,hardMaxTurns:false,hardUsageCap:false,filesystemSandbox:false,nativeRetries:'runtime-managed'};
export function validate(spec){
  if(!spec.model || typeof spec.model!=='string')throw failure('INVALID_MODEL','An explicit native model ID is required');
  if(spec.maxTurns!==undefined)throw failure('UNSUPPORTED_CONTROL','This runtime cannot enforce a hard maxTurns limit');
  if(spec.allowedPaths?.length)throw failure('UNSUPPORTED_CONTROL','allowedPaths requires filesystem isolation unavailable in this runtime');
  if(!['read-only','workspace-write'].includes(spec.mode))throw failure('INVALID_MODE','mode must be read-only or workspace-write');
  if(!Number.isSafeInteger(spec.timeoutMs)||spec.timeoutMs<=0)throw failure('INVALID_TIMEOUT','A positive timeoutMs is required');
}
export function classify(message){
  if(/(?:credit|quota|balance|积分|额度).*(?:exhaust|insufficient|不足|用尽)|hard_credit/i.test(message))return 'CREDITS_EXHAUSTED';
  if(/429|rate.?limit|soft_rate|限流/i.test(message))return 'RATE_LIMIT';
  if(/401|403|unauthori|authentication|session_dead|signed.out|not logged|登录|鉴权/i.test(message))return 'AUTH_ERROR';
  return 'PROVIDER_ERROR';
}
export async function executable(command){
  if(path.isAbsolute(command)||command.includes('/')||command.includes('\\')){try{await access(command);return command;}catch{return undefined;}}
  const extensions=process.platform==='win32'?['.exe','.com','.cmd','.bat','']:[''];
  for(const directory of (process.env.PATH||'').split(path.delimiter))for(const ext of extensions){const candidate=path.join(directory,command+ext);try{await access(candidate);return candidate;}catch{}}
}
export async function execute(options){const {runProcess}=await import('../process.mjs');return runProcess(options);}
export function jsonLines(onValue){let buffer='';function parse(line){let value;try{value=JSON.parse(line);}catch{return;}onValue(value);}return {push(chunk){buffer+=chunk;if(buffer.length>8*1024*1024)throw failure('OUTPUT_TOO_LARGE','Native output line exceeded 8 MiB');let n;while((n=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,n).trim();buffer=buffer.slice(n+1);if(line)parse(line);}},end(){if(buffer.trim())parse(buffer);buffer='';}};}
export async function localModels(provider,config){
  if(!config.modelsFile)return {provider,source:'unavailable-local-cache',models:[]};
  const document=JSON.parse(await readFile(config.modelsFile,'utf8'));
  const models=Array.isArray(document)?document:document.models;
  if(!Array.isArray(models))throw failure('INVALID_CATALOG','Local model cache must contain a models array');
  return {provider,source:'configured-local-cache',fetchedAt:document.fetchedAt,models:models.filter(m=>typeof m.id==='string').map(m=>({id:m.id,name:m.name||m.id,...(m.billing?{billing:m.billing}:{})}))};
}

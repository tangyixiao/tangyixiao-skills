import {mkdtemp,rm,access} from 'node:fs/promises';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {capabilities,executable,failure,localModels,validate} from './common.mjs';
import {createOpenCode} from './opencode.mjs';

function modulePath(config){return config.connectModule||path.join(homedir(),'.dsh','profiles','desktop','node_modules','dsh-workbuddy-connect-community','lib','index.js');}
async function load(config){return import(pathToFileURL(modulePath(config)).href);}
async function resources(provider,config){
  const mod=await load(config),variant=provider==='workbuddy'?mod.CN_VARIANT:mod.AI_VARIANT;
  const directory=await mkdtemp(path.join(tmpdir(),'external-workbuddy-'));
  const client=new mod.WorkBuddyUpstreamClient();
  const store=new mod.WorkBuddyCredentialStore({variant,desktopPath:config.authFile,ownPath:path.join(directory,'auth.json'),refresh:c=>client.refreshToken(c)});
  return {mod,variant,client,store,directory,async close(){await rm(directory,{recursive:true,force:true});}};
}
async function currentCatalog(r,config,refresh,signal){
  const credential=await r.store.current();
  if(!credential)throw failure('AUTH_ERROR','This WorkBuddy variant has no readable desktop credential');
  if(signal?.aborted)throw signal.reason;
  if(refresh)return {models:await r.client.fetchModels(credential,signal),source:'workbuddy-current-account-live-metadata',fetchedAt:new Date().toISOString()};
  const file=config.catalogFile||r.mod.workbuddyCatalogPath(r.variant.catalogFilename);
  const saved=new r.mod.WorkBuddyCatalogStore(file).get(`${credential.uid}:${credential.enterpriseId??''}`);
  if(!saved)throw failure('CATALOG_UNAVAILABLE','No catalog for the current account; refresh model metadata explicitly first');
  return {models:saved.models,source:'workbuddy-current-account-local-cache',fetchedAt:new Date(saved.fetchedAtMs).toISOString()};
}
export function createWorkBuddy(provider,config={}){return {
  async doctor(){let mod,installed=false;try{await access(modulePath(config));mod=await load(config);installed=true;}catch{}let present=false;if(mod){const variant=provider==='workbuddy'?mod.CN_VARIANT:mod.AI_VARIANT;for(const file of config.authFile?[config.authFile]:mod.desktopAuthCandidatesFor(variant)){try{await access(file);present=true;break;}catch{}}}return {provider,installed,launchable:installed&&!!await executable(config.command||'opencode'),authStatus:present?'credential-file-present-unverified':'credential-file-not-found',taskVerified:false,capabilities,details:{offline:true,connectImport:installed,credentialContentsRead:false,upstreamContacted:false}};},
  async listModels({config:override,refresh=false}={}){const c=override||config;if(c.modelsFile&&!refresh)return localModels(provider,c);if(!refresh)return {provider,source:'current-account-cache-requires-credential-read',models:[],details:'Use explicit refresh to authorize current-account metadata lookup, or provide modelsFile'};const r=await resources(provider,c);try{return {provider,...await currentCatalog(r,c,true,AbortSignal.timeout(c.metadataTimeoutMs||20000))};}finally{await r.close();}},
  async run(spec,ctx){validate(spec);if(ctx.signal?.aborted)throw ctx.signal.reason;const r=await resources(provider,config);let shim;try{const data=await currentCatalog(r,config,true,ctx.signal);const model=data.models.find(m=>m.id===spec.model);if(!model)throw failure('INVALID_MODEL','Chosen model is absent from the current account catalog');const catalog=new r.mod.WorkBuddyCatalog(data.models);shim=r.mod.createWorkBuddyShim({store:r.store,client:r.client,catalog,logger:{warn(){},error(){}}});const abort=()=>{void shim.close();};ctx.signal?.addEventListener('abort',abort,{once:true});try{await shim.ready;if(ctx.signal?.aborted)throw ctx.signal.reason;const runtimeConfig={enabled_providers:[provider],provider:{[provider]:{npm:'@ai-sdk/openai-compatible',name:provider,options:{baseURL:`${shim.baseUrl()}/v1`,apiKey:shim.token()},models:{[spec.model]:{name:model.name||spec.model,limit:{context:model.contextWindow||128000,output:model.maxTokens||8192}}}}}};return await createOpenCode({...config,runtimeConfig},provider).run({...spec,model:`${provider}/${spec.model}`},ctx);}finally{ctx.signal?.removeEventListener('abort',abort);}}finally{if(shim)await shim.close();await r.close();}}
};}

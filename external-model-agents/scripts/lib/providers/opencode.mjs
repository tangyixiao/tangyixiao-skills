import {capabilities,classify,execute,executable,failure,jsonLines,localModels,validate} from './common.mjs';

export function permissions(mode){return {'*':'deny',read:'allow',glob:'allow',grep:'allow',list:'allow',edit:mode==='workspace-write'?'allow':'deny',write:mode==='workspace-write'?'allow':'deny',bash:'deny',task:'deny',external_directory:'deny',webfetch:'deny',websearch:'deny',question:'deny'};}
export function runtimeConfig(mode,overlay={}){return {...overlay,permission:permissions(mode),agent:{...overlay.agent,'external-model-agent':{mode:'primary',permission:permissions(mode)},title:{disable:true},summary:{disable:true},compaction:{disable:true}},compaction:{auto:false,prune:false}};}
export function createOpenCode(config={},provider='opencode'){
  const command=config.command||'opencode';
  return {
    async doctor(){const installed=!!await executable(command);return {provider,installed,launchable:false,authStatus:'unverified',taskVerified:false,capabilities,details:{offline:true,launchability:'not-executed',runtime:command}};},
    async listModels({config:override,refresh=false}={}){
      const c=override||config;
      if(!refresh)return localModels(provider,c);
      let output='',errors='';const r=await execute({command:c.command||command,args:[...(c.commandArgs||[]),'--pure','models','--verbose'],cwd:c.cwd||process.cwd(),env:{...process.env},signal:AbortSignal.timeout(c.metadataTimeoutMs||15000),onStdout:s=>output+=s,onStderr:s=>errors+=s});
      if(r.exitCode!==0)throw failure(classify(errors),`Model metadata refresh failed: ${errors}`);
      const models=[];const starts=[...output.matchAll(/^([\w.-]+\/\S+)\r?$/gm)];for(let i=0;i<starts.length;i++){const id=starts[i][1];let metadata={};try{metadata=JSON.parse(output.slice(starts[i].index+starts[i][0].length,starts[i+1]?.index??output.length).trim());}catch{}models.push({id,name:metadata.name||id,...Object.fromEntries(['cost','limit','capabilities','status'].filter(k=>metadata[k]!==undefined).map(k=>[k,metadata[k]]))});}
      return {provider,source:'opencode-configured-runtime-metadata',fetchedAt:new Date().toISOString(),models};
    },
    async run(spec,ctx){
      validate(spec);
      const args=[...(config.commandArgs||[]),'--pure','run','--format','json','--model',spec.model,'--agent','external-model-agent'];
      if(spec.sessionId)args.push('--session',spec.sessionId);
      args.push('--',spec.prompt);
      let text='',sessionId=spec.sessionId,errorText='',errorEvent,blocked=false,toolSuccess=false,pending=Promise.resolve();const usageSteps=[];
      await ctx.emit({type:'provider_model',provider,model:spec.model});
      const parser=jsonLines(event=>{pending=pending.then(async()=>{await ctx.emit(event);const sid=event.sessionID||event.sessionId;if(sid){sessionId=sid;await ctx.onSession(sid);}if(event.type==='text'&&typeof event.part?.text==='string')text+=event.part.text;if(event.type==='error')errorEvent=event.error||event;if(/permission|userInput|question/.test(event.type||''))blocked=true;if(event.type==='tool_use'&&event.part?.state?.status==='completed')toolSuccess=true;if(event.type==='step_finish')usageSteps.push({tokens:event.part?.tokens,cost:event.part?.cost});});pending.catch(()=>{});});
      const env={...process.env,OPENCODE_CONFIG_CONTENT:JSON.stringify(runtimeConfig(spec.mode,config.runtimeConfig||{})),OPENCODE_DISABLE_AUTOUPDATE:'true',OPENCODE_DISABLE_MODELS_FETCH:'true'};
      const result=await execute({command,args,cwd:spec.cwd,env,signal:ctx.signal,onStdout:s=>parser.push(s),onStderr:s=>{errorText+=s;ctx.emit({type:'stderr',text:s});}});
      parser.end();await pending;
      if(blocked)return {text,sessionId,outcome:'awaiting_input'};
      if(result.exitCode!==0||errorEvent){const detail=JSON.stringify(errorEvent||errorText||`OpenCode exited ${result.exitCode}`);throw failure(classify(detail),detail);}
      if(!text.trim()&&!toolSuccess)throw failure('EMPTY_RESULT','OpenCode exited without substantive text or a completed tool');
      return {text,sessionId,toolEvidence:toolSuccess,...(usageSteps.length?{usage:{steps:usageSteps}}:{}),outcome:'completed'};
    }
  };
}

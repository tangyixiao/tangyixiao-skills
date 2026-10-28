import {createOpenCode} from './opencode.mjs';
import {createWorkBuddy} from './workbuddy.mjs';
import {createZCode} from './zcode.mjs';
export const providerNames=['workbuddy','workbuddy-ai','opencode','zcode'];
export function getAdapter(provider,config={}){if(provider==='opencode')return createOpenCode(config);if(provider==='zcode')return createZCode(config);if(provider==='workbuddy'||provider==='workbuddy-ai')return createWorkBuddy(provider,config);throw new Error(`Unknown provider: ${provider}`);}

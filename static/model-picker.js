import {t as tr} from './i18n.js';
import {esc} from './markdown.js';
export const configureModelValue='__configure_models__';
export function trialModel(model){return (model.providerID||model.id.split('/')[0])==='trial';}
export function modelUsable(model,catalog){return !!model&&!(trialModel(model)&&catalog.trial_remaining===0);}
export function availableModel(catalog,selected=catalog.selected){
  return (catalog.models.find(m=>m.id===selected&&modelUsable(m,catalog))||catalog.models.find(m=>modelUsable(m,catalog)))?.id||null;
}
export function modelOptionsHTML(catalog){
  const exhausted=catalog.trial_remaining===0&&catalog.models.some(trialModel);
  const selected=catalog.models.find(m=>m.id===catalog.selected);
  const placeholder=modelUsable(selected,catalog)?'':`<option value="">${esc(tr('请选择可用模型'))}</option>`;
  return placeholder+catalog.models.map(m=>{
    const provider=trialModel(m)?tr('试用'):(m.providerLabel||m.providerID||m.id.split('/')[0]);
    return `<option value="${esc(m.id)}"${modelUsable(m,catalog)?'':' disabled'}>${esc(m.label)} · ${esc(provider)}</option>`;
  }).join('')+(exhausted?`<option value="${configureModelValue}">${esc(tr('试用次数已用完，配置自己的模型'))}</option>`:'');
}

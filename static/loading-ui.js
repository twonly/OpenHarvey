import {esc} from './markdown.js';

export function loadingHTML(text){
  return `<span class="loading-status" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>${esc(text)}</span></span>`;
}

export function setLoadingStatus(element,text,busy=false){
  element.classList.toggle('loading-status',busy);
  element.setAttribute('aria-busy',String(busy));
  if(busy)element.innerHTML=`<span class="loading-spinner" aria-hidden="true"></span><span>${esc(text)}</span>`;
  else element.textContent=text;
}

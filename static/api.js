import {t as tr,ui} from './i18n.js';

export async function confirmSession(fetcher, signal){
  const response=await fetcher('/api/me',{credentials:'same-origin',cache:'no-store',signal});
  return response.status===401?'expired':response.ok?'valid':'unavailable';
}
export async function api(path, {method='GET', body, headers={}, signal, timeout=method==='GET'?30000:120000}={}) {
  const controller=new AbortController();
  const abort=()=>controller.abort(signal.reason);
  if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(()=>controller.abort(new DOMException(tr('请求等待超时'),'TimeoutError')),timeout);
  const options = {method, credentials:'same-origin', headers:{...headers},signal:controller.signal};
  try{
  if (method !== 'GET') options.headers['X-Workbench-Request']='1';
  if (body instanceof File || body instanceof Blob) options.body=body;
  else if (body !== undefined) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body); }
  let response=await fetch(path, options);
  if(response.status===401 && path!=='/api/login' && !path.startsWith('/api/auth/')){
    // A delayed response can refer to an older login. Confirm using the current
    // browser cookie before discarding the workspace; never replay writes.
    const session=await confirmSession(fetch,controller.signal);
    if(controller.signal.aborted)throw controller.signal.reason;
    if(session==='expired')document.dispatchEvent(new Event('session-expired'));
    else if(session==='valid'&&method==='GET')response=await fetch(path,options);
    else {
      const error=new Error(tr(session==='valid'?'登录仍然有效，请重试本次操作。':'暂时无法确认登录状态，请重试。'));
      error.status=503;throw error;
    }
    if(session==='valid'&&response.status===401){
      const error=new Error(tr('登录仍然有效，请重试本次操作。'));error.status=503;throw error;
    }
  }
  if(!response.ok){
    const data=await response.json().catch(()=>({}));
    const error=new Error(typeof data.detail==='string'?data.detail:ui`请求失败（${response.status}）`);
    if(method!=='GET'&&response.status===403&&/注册/.test(error.message))document.dispatchEvent(new CustomEvent('registration-required',{detail:error.message}));
    error.message=tr(error.message);error.status=response.status;throw error;
  }
  if(response.status===204) return null;
  if(response.status===202 && !response.headers.get('content-type')?.includes('application/json')) return null;
  const result=await response.json();if(method!=='GET'&&path.startsWith('/api/threads/'))document.dispatchEvent(new Event('usage-changed'));return result;
  }catch(error){
    if(signal?.aborted)throw new DOMException(tr('已切换对话'),'AbortError');
    if(controller.signal.aborted)throw new Error(method==='GET'?tr('读取超时，请点击当前对话重试。'):tr('请求超时，结果尚未确认，请先刷新查看是否已保存。'));
    if(error instanceof TypeError)throw new Error(method==='GET'?tr('网络连接中断，请重试。'):tr('网络连接中断，结果尚未确认，请先刷新查看是否已保存。'));
    throw error;
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}

export function upload(path,file){
  return api(path,{method:'POST',body:file,headers:{'X-Filename':encodeURIComponent(file.name)}});
}

import {t as tr} from './i18n.js';

export function redlineLabsHTML(status){
  const message=status.requires_login?'登录正式账号后可开启 DOCX 审改。':!status.available?'DOCX 审改暂不可用，请稍后重试。':status.effective?'已开启：打开 DOCX 合同，点击“审改”即可使用。':'尚未开启。开启后即可在工作台审改 DOCX 合同。';
  return `<section class="memory-labs redline-labs"><header><div><h3>${tr('DOCX 审改')}</h3><p>${tr('和 Agent 一起修改合同，在原文中审阅修订与批注。')}</p></div><label class="settings-check"><input type="checkbox" data-redline-toggle aria-label="${tr('开启 DOCX 审改')}" ${status.redline_enabled?'checked':''} ${!status.available?'disabled':''}>${tr('开启')}</label></header><p class="settings-note" role="status">${tr(message)}</p>${status.requires_login?`<a href="/login">${tr('登录正式账号')}</a>`:''}<ul class="labs-description"><li>${tr('圈选条款交给 Agent；明确要求修改后，直接保存为待审修订。')}</li><li>${tr('修订、批注与正文联动定位；逐项接受或拒绝修改，独立回复或解决批注。')}</li><li>${tr('自动保存工作稿，按目录定位，命名重要版本、查看历史或恢复；上传原件始终保留。')}</li><li>${tr('可下载修订版；处理完所有待审修订后可导出清洁版，批注仅从交付副本移除。')}</li></ul><details><summary>${tr('适用范围与关闭说明')}</summary><p class="settings-note">${tr('目前支持 DOCX 单人编辑，不支持多人实时协作。PDF 仍用于阅读、分析和建议；复杂排版兼容性仍在验证，不支持跨段落合并或拆分修订。')}</p><p class="settings-note">${tr('关闭会停用网页审改与 Agent 文档修改，不删除已保存的工作稿、修订、批注或版本。重新开启后可继续。请先保存并关闭其他审改窗口；正在写入的任务需完成后再关闭。')}</p></details></section>`;
}

export function announceLabsChange(){
  document.dispatchEvent(new Event('labs-changed'));
  try{localStorage.setItem('labs-change',String(Date.now()));}catch{}
}

import {t as tr,ui} from './i18n.js';
import {getLanguage} from './i18n.js';
import {esc,markdown} from './markdown.js';

export const decisions=['待处理','要求修改','接受风险','升级审批','补充材料','判断有误'];
export function riskStatus(f){return f.applicable===false?'不适用':f.verdict;}
export function riskCounts(findings){
  const counts={'命中':0,'信息不足':0,'未命中':0,'不适用':0};
  for(const f of findings)counts[riskStatus(f)]=(counts[riskStatus(f)]||0)+1;
  return counts;
}
export function riskBoard(data,documents,filter='attention'){
  const findings=data.findings||[],counts=riskCounts(findings),feedback=data.feedback||{};
  const attention=counts['命中']+counts['信息不足'];
  const filters=[['attention',ui`需关注 ${attention}`],['all',ui`全部 ${findings.length}`],['未命中',ui`未命中 ${counts['未命中']}`],['不适用',ui`不适用 ${counts['不适用']}`],['handled',tr('已反馈')]];
  const visible=findings.filter(f=>filter==='all'||(filter==='attention'?['命中','信息不足'].includes(riskStatus(f)):filter==='handled'?feedback[f.risk_id]?.decision&&feedback[f.risk_id].decision!=='待处理':riskStatus(f)===filter));
  return ui`<section class="risk-board" data-risk-board="${esc(data.id)}" data-risk-filter="${esc(filter)}">
    <header class="risk-overview"><div><h3>审查结果</h3><p>已检查 ${findings.length} 项 · ${counts['命中']} 项风险 · ${counts['信息不足']} 项待补充</p></div><span class="review-perspective">${esc(data.perspective||'乙方')}立场</span></header>
    <nav class="risk-filters" aria-label="筛选审查结果">${filters.map(([id,label])=>`<button data-risk-filter-choice="${esc(id)}" aria-pressed="${id===filter}">${label}</button>`).join('')}</nav>
    <div class="risk-list">${visible.map(f=>{
      const saved=feedback[f.risk_id]||{decision:'待处理',note:'',revision:0,history:[]},status=riskStatus(f);
      return ui`<article class="review-risk" data-risk-id="${esc(f.risk_id)}" data-verdict="${esc(status)}">
        <header><span class="risk-verdict">${esc(tr(status))}</span><h4>${esc(f.risk_name||f.risk_id)}</h4><span class="risk-severity" data-level="${esc(f.severity)}">${esc(f.severity?tr(f.severity):tr('未分级'))}${f.severity?tr('风险'):''}</span></header>
        <div class="risk-meta">${esc(f.category||'')} · ${esc(f.risk_id)}<span class="disposition">${esc(tr(saved.decision))}</span></div>
        <div class="risk-reason markdown">${markdown(f.reason,documents)}</div>
        ${f.suggestion?ui`<div class="risk-suggestion markdown"><b>建议</b>${markdown(f.suggestion,documents)}</div>`:''}
        <details class="risk-feedback"><summary>${saved.revision?tr('查看 / 修改处理意见'):tr('添加处理意见')}${saved.note?' · '+esc(saved.note.slice(0,35)):''}</summary>
          <form data-risk-feedback="${esc(f.risk_id)}" data-revision="${saved.revision}">
            <label>处理方式<select name="decision" aria-label="${esc(f.risk_name||f.risk_id)}处理方式">${decisions.map(d=>`<option value="${esc(d)}"${saved.decision===d?' selected':''}>${esc(tr(d))}</option>`).join('')}</select></label>
            <label>备注<textarea name="note" maxlength="1000" rows="2" placeholder="处置理由、修正依据或需补充的材料">${esc(saved.note)}</textarea></label>
            <p class="feedback-help">处理意见单独保存，原审查结论会保留。接受风险不代表判断有误。</p>
            <div class="feedback-actions"><button type="submit" class="feedback-save">保存反馈</button></div><p class="feedback-status" role="status"></p>
          </form>
          ${saved.revision?ui`<details class="feedback-history"><summary>反馈记录（${saved.history.length+1}）</summary>${[...saved.history,saved].reverse().map(h=>`<p><b>${esc(tr(h.decision))}</b> · ${new Date(h.created*1000).toLocaleString(getLanguage())}<br>${esc(h.note||tr('无备注'))}</p>`).join('')}</details>`:''}
        </details>
      </article>`;
    }).join('')||tr('<p class="risk-empty">这个筛选下没有审查项。</p>')}</div>
  </section>`;
}

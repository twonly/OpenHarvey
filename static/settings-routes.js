export const settingsPaths={general:'/config',skills:'/skills',risks:'/risks',traces:'/traces',providers:'/model',members:'/members',connectors:'/connectors'};
export function settingsTab(path){return Object.keys(settingsPaths).find(tab=>settingsPaths[tab]===path.replace(/\/$/,''))||null;}
export function savedWorkbenchURL(value){return /^\/agent#[a-f0-9]+\/thread\/[a-f0-9]+$/.test(value||'')?value:'/spaces';}

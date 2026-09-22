import {build} from 'esbuild';
import {mkdir,copyFile,writeFile} from 'node:fs/promises';
const out='static/vendor';await mkdir(out,{recursive:true});
await build({stdin:{contents:"export {SuperDoc} from 'superdoc'; export {createSuperDocUI} from 'superdoc/ui'; import 'superdoc/style.css';",resolveDir:process.cwd()},bundle:true,format:'esm',minify:true,outfile:out+'/redline-editor.js',loader:{'.png':'dataurl','.svg':'dataurl','.woff2':'dataurl'},legalComments:'linked',define:{__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false'}});
await copyFile('node_modules/superdoc/LICENSE',out+'/SuperDoc-LICENSE.txt');
await writeFile(out+'/README.txt','SuperDoc 1.46.3 (AGPL-3.0), self-hosted browser bundle. Source: https://github.com/superdoc/docx-editor . Built with npm run build:redline. Do not update to v2 without reviewing the proprietary docx-engine dependency.\n');

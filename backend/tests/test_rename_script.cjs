const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
function scenario(options = {}) {
  const root = {getId: () => '10WDNKBJMtuwwGiVD6p1OhSOG9jQcNq-f'};
  const iterator = items => ({hasNext: () => items.length > 0, next: () => items.shift()});
  const parent = {getId: () => 'source', getName: () => '2026_09_17', getParents: () => iterator([options.foreign ? {getId: () => 'other'} : root])};
  const dest = {getId: () => 'dest', getName: () => 'Переименовано', getParents: () => iterator([parent]), getFilesByName: () => iterator(options.collision ? [{getId: () => 'other-image'}] : [])};
  let name = options.newName ? 'SS-25_BRAND_123_BLACK_0.jpg' : '123_BLACK_0.jpg';
  let location = options.done ? dest : parent;
  let renames = 0, moves = 0;
  const image = {getId: () => 'photo', getName: () => name, getMimeType: () => 'image/jpeg', isTrashed: () => false,
    getParents: () => iterator([location]), setName: n => {name=n;renames++;}, moveTo: d => {location=d;moves++;}};
  const context = {DriveApp: {getFolderById: id => id==='source' ? parent : dest, getFileById: () => image}, Date, ContentService: {}, console};
  vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/../rename_api.gs','utf8'),context);
  const op = {id:'photo',parent:'source',destination:'dest',day:'2026_09_17',name:'123_BLACK_0.jpg',new_name:'SS-25_BRAND_123_BLACK_0.jpg'};
  return {context,op,counts:()=>({renames,moves})};
}
let s=scenario();s.context.renameOneExact_(s.op);assert.equal(s.op.status,'completed');assert.deepEqual(s.counts(),{renames:1,moves:1});
s=scenario({newName:true});s.context.renameOneExact_(s.op);assert.deepEqual(s.counts(),{renames:0,moves:1});
s=scenario({newName:true,done:true});s.context.renameOneExact_(s.op);assert.deepEqual(s.counts(),{renames:0,moves:0});
s=scenario({collision:true});assert.throws(()=>s.context.renameOneExact_(s.op),/collision/);assert.deepEqual(s.counts(),{renames:0,moves:0});
s=scenario({foreign:true});assert.throws(()=>s.context.renameOneExact_(s.op),/Folder differs/);assert.deepEqual(s.counts(),{renames:0,moves:0});
s=scenario();s.op.name='123_BLACK_0_ПРОВЕРИТЬ_БИРКУ.jpg';assert.throws(()=>s.context.renameOneExact_(s.op),/Unsafe/);
s=scenario();s.op.name='unexpected.jpg';assert.throws(()=>s.context.renameOneExact_(s.op),/name changed/);
console.log('7 safety/restart scenarios passed');

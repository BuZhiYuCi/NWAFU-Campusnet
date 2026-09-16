/*
 * 用门户官方前端源码生成加密测试向量，供 Python 实现做回归比对。
 *
 * 用法:
 *   node tools/js_reference.js <all.min.js 路径> > tests/vectors.json
 *
 * all.min.js 来自门户 (注意：带 ?v=xxx 查询串会返回空内容，去掉即可):
 *   http://172.26.8.11/static/themes/pro/lib/all.min.js
 *
 * 本脚本不重写任何算法，全部直接 eval 官方源码：
 *   - js-md5 库      -> 官方 md5(password, token) 的双参数 HMAC 语义
 *   - jquery-base64  -> 官方自定义字母表 base64（注意：逐 byte 映射，不做 UTF-8 转换）
 *   - s / l / encode -> 从 Portal.js 逐字复制
 */
'use strict';

const fs = require('fs');
const vm = require('vm');
const crypto = require('crypto');

const srcPath = process.argv[2];
if (!srcPath) {
  console.error('用法: node tools/js_reference.js <all.min.js 路径>');
  process.exit(2);
}
const src = fs.readFileSync(srcPath, 'utf8');

function slice(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error('找不到起始标记: ' + startMarker);
  const b = src.indexOf(endMarker, a + 1);
  if (b < 0) throw new Error('找不到结束标记: ' + endMarker);
  return src.slice(a, b);
}

// ---- 官方 js-md5 (md5 v2.10.0) ----
const md5Sandbox = { module: { exports: {} }, console: console };
vm.createContext(md5Sandbox);
vm.runInContext(slice('//md5 v2.10.0', '//js-sha1 v0.6.0'), md5Sandbox);
const md5 = md5Sandbox.module.exports;

// ---- 官方 jquery-base64 (jquery-base64 v1.0，默认字母表即 srun 自定义表) ----
const b64Sandbox = { module: { exports: {} }, jQuery: {}, console: console };
vm.createContext(b64Sandbox);
vm.runInContext(slice('//jquery-base64 v1.0', '//jquery qrcode 1.0'), b64Sandbox);
const base64 = b64Sandbox.jQuery.base64;
const ALPHA = 'LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA';
base64.setAlpha(ALPHA);

// ---- 以下 s / l / encode 逐字复制自 Portal.js 的 _encodeUserInfo ----
function s(a, b) {
  var c = a.length;
  var v = [];

  for (var i = 0; i < c; i += 4) {
    v[i >> 2] = a.charCodeAt(i) | a.charCodeAt(i + 1) << 8 | a.charCodeAt(i + 2) << 16 | a.charCodeAt(i + 3) << 24;
  }

  if (b) v[v.length] = c;
  return v;
}

function l(a, b) {
  var d = a.length;
  var c = d - 1 << 2;

  if (b) {
    var m = a[d - 1];
    if (m < c - 3 || m > c) return null;
    c = m;
  }

  for (var i = 0; i < d; i++) {
    a[i] = String.fromCharCode(a[i] & 0xff, a[i] >>> 8 & 0xff, a[i] >>> 16 & 0xff, a[i] >>> 24 & 0xff);
  }

  return b ? a.join('').substring(0, c) : a.join('');
}

function encode(str, key) {
  if (str === '') return '';
  var v = s(str, true);
  var k = s(key, false);
  if (k.length < 4) k.length = 4;
  var n = v.length - 1,
      z = v[n],
      y = v[0],
      c = 0x86014019 | 0x183639A0,
      m,
      e,
      p,
      q = Math.floor(6 + 52 / (n + 1)),
      d = 0;

  while (0 < q--) {
    d = d + c & (0x8CE0D9BF | 0x731F2640);
    e = d >>> 2 & 3;

    for (p = 0; p < n; p++) {
      y = v[p + 1];
      m = z >>> 5 ^ y << 2;
      m += y >>> 3 ^ z << 4 ^ (d ^ y);
      m += k[p & 3 ^ e] ^ z;
      z = v[p] = v[p] + m & (0xEFB8D130 | 0x10472ECF);
    }

    y = v[0];
    m = z >>> 5 ^ y << 2;
    m += y >>> 3 ^ z << 4 ^ (d ^ y);
    m += k[p & 3 ^ e] ^ z;
    z = v[n] = v[n] + m & (0xBB390742 | 0x44C6F8BD);
  }

  return l(v, false);
}

// ---- 与 Portal.js 完全一致的组装方式 ----
function encodeUserInfo(info, token) {
  return '{SRBX1}' + base64.encode(encode(JSON.stringify(info), token));
}

function sha1Hex(str) {
  return crypto.createHash('sha1').update(str, 'utf8').digest('hex');
}

function md5Hex(str) {
  return crypto.createHash('md5').update(str, 'utf8').digest('hex');
}

function hmacMd5Hex(key, msg) {
  return crypto.createHmac('md5', Buffer.from(key, 'utf8')).update(Buffer.from(msg, 'utf8')).digest('hex');
}

const cases = [
  { token: 'c436b50ea8065baf5e938b4a5c334cc374af9faf952a60aa27f31e647c402d12',
    username: '17782817252', password: 'Test-Pass-A1', ip: '10.128.96.98', acid: '1' },
  { token: '0f8afd7ea13f9ec8dbbac4d68ff10f467578da86c77f2369b58b0fa5298a573b',
    username: '17782817252@yx-s-student', password: 'unit-test-xyz', ip: '10.111.147.127', acid: '1' },
  { token: 'shortToken123', username: 'u2', password: 'p2', ip: '10.0.0.1', acid: '2' },
  { token: 'B', username: 'a', password: 'b', ip: '1.2.3.4', acid: '1' },
  { token: '1234567890abcdef', username: 'abcdefg', password: '', ip: '10.9.8.7', acid: '10' }
];

const out = cases.map(function (c) {
  const info = { username: c.username, password: c.password, ip: c.ip, acid: c.acid, enc_ver: 'srun_bx1' };
  const n = 200, type = 1;
  const hmd5Hmac = md5(c.password, c.token);            // 官方调用形式: 双参数
  const hmacCheck = hmacMd5Hex(c.token, c.password);    // 本脚本用 Node crypto 复核
  const concatCheck = md5Hex(c.password + c.token);     // 单参数拼接写法（对照）
  const encoded = encodeUserInfo(info, c.token);
  const str = c.token + c.username + c.token + hmd5Hmac + c.token + c.acid +
              c.token + c.ip + c.token + n + c.token + type + c.token + encoded;
  return {
    token: c.token,
    username: c.username,
    password: c.password,
    ip: c.ip,
    acid: c.acid,
    enc_ver: 'srun_bx1',
    json: JSON.stringify(info),
    info: encoded,
    hmd5_hmac: hmd5Hmac,
    hmd5_hmac_check: hmacCheck,
    hmd5_concat: concatCheck,
    chksum: sha1Hex(str)
  };
});

console.log(JSON.stringify({ source: 'srun portal 2.00.20210607', vectors: out }, null, 2));

#!/usr/bin/env node
// Builds the relocatable desktop runtime under client/build/:
//
//   build/python/   python-build-standalone (PBS) CPython + production deps
//   build/bin/      pinned static ffmpeg for the current platform
//   build/THIRD-PARTY-NOTICES.md
//
// The whole tree is mapped into the packaged app via electron-builder
// extraResources and must stay self-contained: no venv, no absolute paths,
// no reliance on a system Python or ffmpeg.
//
// All downloads are pinned to an exact version and verified against a
// sha256 constant. Never point these at a rolling "latest" URL.
//
// Usage:
//   node scripts/build-python-runtime.mjs [--clean] [--platform darwin|win32] [--arch arm64|x64]
//
// --platform/--arch override the host triple (electron-builder builds are
// per-runner, so cross-builds are only useful for debugging).

import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  chmodSync,
  copyFileSync,
  createReadStream,
  createWriteStream,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const clientRoot = path.resolve(__dirname, '..')
const serverRoot = path.resolve(clientRoot, '..', 'server')
const buildDir = path.join(clientRoot, 'build')
const cacheDir = path.join(buildDir, 'cache')
const pythonDir = path.join(buildDir, 'python')
const binDir = path.join(buildDir, 'bin')
const runtimeMarker = path.join(pythonDir, '.comicagent-runtime.json')

// ---------------------------------------------------------------------------
// Pinned artifacts
// ---------------------------------------------------------------------------

// server/requirements.lock is compiled for Python 3.11, so stay on 3.11.x.
const PBS_PYTHON_VERSION = '3.11.16'
const PBS_RELEASE_TAG = '20260901'
const PBS_VARIANT = 'install_only_stripped'
const PBS_ASSETS = {
  'darwin-arm64': {
    triple: 'aarch64-apple-darwin',
    sha256: '768f05cf200273bbdda9a5955a5a6892a4b22f2a0b1e4b0a9160f5c7fce86816',
  },
  'darwin-x64': {
    triple: 'x86_64-apple-darwin',
    sha256: '908b381433f78b832c8d64960ced0f85871893cc8779f413f963e0c9e293c258',
  },
  'win32-x64': {
    triple: 'x86_64-pc-windows-msvc',
    sha256: '06cbe479e039f5b9cb5640c286d790074d63f549f92a32d599a3748293bd4510',
  },
}

// ffmpeg-static publishes single-file static builds for every desktop
// platform with per-asset checksums. The server encodes with libx264
// (services/ffmpeg_service.py), so the build must be a GPL flavour that
// bundles libx264; LGPL-only builds would fail with "Unknown encoder".
const FFMPEG_TAG = 'b6.1.1'
const FFMPEG_VERSION = '6.0'
const FFMPEG_ASSETS = {
  'darwin-arm64': {
    name: 'ffmpeg-darwin-arm64',
    sha256: 'a90e3db6a3fd35f6074b013f948b1aa45b31c6375489d39e572bea3f18336584',
  },
  'darwin-x64': {
    name: 'ffmpeg-darwin-x64',
    sha256: 'ebdddc936f61e14049a2d4b549a412b8a40deeff6540e58a9f2a2da9e6b18894',
  },
  'win32-x64': {
    name: 'ffmpeg-win32-x64',
    sha256: '04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00',
  },
}

function pbsAssetName(asset) {
  return `cpython-${PBS_PYTHON_VERSION}+${PBS_RELEASE_TAG}-${asset.triple}-${PBS_VARIANT}.tar.gz`
}

function pbsUrl(asset) {
  const name = pbsAssetName(asset)
  return `https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE_TAG}/${encodeURIComponent(name)}`
}

function ffmpegUrl(asset) {
  return `https://github.com/eugeneware/ffmpeg-static/releases/download/${FFMPEG_TAG}/${asset.name}`
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function log(msg) {
  console.log(`[build-runtime] ${msg}`)
}

function fail(msg) {
  console.error(`[build-runtime] 错误: ${msg}`)
  process.exit(1)
}

function parseArgs(argv) {
  const args = { clean: false, platform: undefined, arch: undefined }
  for (const raw of argv) {
    if (raw === '--clean') args.clean = true
    else if (raw.startsWith('--platform=')) args.platform = raw.slice('--platform='.length)
    else if (raw.startsWith('--arch=')) args.arch = raw.slice('--arch='.length)
    else fail(`未知参数: ${raw}`)
  }
  return args
}

function resolveTargetKey(args) {
  const platform = args.platform ?? process.platform
  const arch = args.arch ?? process.arch
  const key = `${platform}-${arch}`
  if (!(key in PBS_ASSETS)) {
    fail(`不支持的平台组合: ${key}(支持: ${Object.keys(PBS_ASSETS).join(', ')})`)
  }
  return key
}

function isWindows(targetKey) {
  return targetKey.startsWith('win32-')
}

function pythonExecutable(dir, targetKey) {
  return isWindows(targetKey)
    ? path.join(dir, 'python.exe')
    : path.join(dir, 'bin', 'python3')
}

async function sha256File(file) {
  const hash = createHash('sha256')
  await pipeline(createReadStream(file), async (source) => {
    for await (const chunk of source) hash.update(chunk)
  })
  return hash.digest('hex')
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function curlAvailable() {
  return run('curl', ['--version'], { stdio: 'pipe' }).status === 0
}

const HAVE_CURL = curlAvailable()

async function download(url, dest) {
  mkdirSync(path.dirname(dest), { recursive: true })
  // curl copes better with flaky links (its retries also cover stalled
  // connects) and ships on macOS, Linux and Windows 10+ alike; keep a
  // fetch fallback for odd environments without it.
  if (HAVE_CURL) {
    const result = run('curl', [
      '--location',
      '--fail',
      '--silent',
      '--show-error',
      '--retry', '10',
      '--retry-all-errors',
      '--retry-delay', '5',
      '--connect-timeout', '30',
      '--output', dest,
      url,
    ], { stdio: 'inherit' })
    if (result.status !== 0) {
      rmSync(dest, { force: true })
      throw new Error(`curl 退出码 ${result.status}`)
    }
    return
  }
  const maxAttempts = 10
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetch(url, { redirect: 'follow' })
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
      await pipeline(Readable.fromWeb(response.body), createWriteStream(dest))
      return
    } catch (error) {
      rmSync(dest, { force: true })
      if (attempt === maxAttempts) throw error
      log(`下载失败(${error.message}),${Math.min(attempt * 5, 30)}s 后重试 ${url}`)
      await wait(Math.min(attempt * 5000, 30000))
    }
  }
}

async function fetchVerified(url, dest, expectedSha256) {
  if (existsSync(dest) && (await sha256File(dest)) === expectedSha256) {
    log(`缓存命中: ${path.basename(dest)}`)
    return
  }
  log(`下载 ${url}`)
  await download(url, dest)
  const actual = await sha256File(dest)
  if (actual !== expectedSha256) {
    rmSync(dest, { force: true })
    fail(`sha256 校验失败: ${path.basename(dest)}\n  期望 ${expectedSha256}\n  实际 ${actual}`)
  }
  log(`sha256 校验通过: ${actual}`)
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: options.stdio ?? 'inherit',
    env: process.env,
    shell: false,
  })
  return result
}

function runInterpreter(interpreter, args) {
  return run(interpreter, ['-c', args.join('\n')], { stdio: 'pipe' })
}

function interpreterCheckCode(dirToExpect) {
  // PBS derives sys.prefix from the interpreter's own location, which is what
  // makes the tree relocatable. Assert the resolved prefix matches the tree
  // we are about to ship.
  return [
    'import os, sys',
    'prefix = os.path.realpath(sys.prefix)',
    `expected = os.path.realpath(${JSON.stringify(dirToExpect)})`,
    'assert prefix == expected, f"sys.prefix {prefix} != {expected}"',
    'assert sys.version_info[:2] == (3, 11), sys.version',
    'print("prefix-ok", prefix, sys.version.split()[0])',
  ]
}

// ---------------------------------------------------------------------------
// Python runtime
// ---------------------------------------------------------------------------

function extractPbs(tarball, stagingDir) {
  // bsdtar ships with Windows 10+ (System32) and macOS/Linux.
  const result = run('tar', ['-xzf', tarball, '-C', stagingDir])
  if (result.status !== 0) fail('解压 PBS 失败(tar 退出码非 0)')
}

function copyTreeDereferenced(source, dest) {
  // PBS macOS archives contain relative symlinks (bin/python3 -> python3.11).
  // Dereferencing avoids dangling symlinks if the packaged tree is copied by
  // a tool that does not preserve them. copyFileSync follows symlink sources
  // and preserves the target's permission bits.
  rmSync(dest, { recursive: true, force: true })
  mkdirSync(dest, { recursive: true })
  const entries = readdirSync(source, { withFileTypes: true })
  for (const entry of entries) {
    const from = path.join(source, entry.name)
    const to = path.join(dest, entry.name)
    if (entry.isDirectory()) copyTreeDereferenced(from, to)
    else copyFileSync(from, to)
  }
}

function removeRecursiveIfExist(dir) {
  if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
}

function slimPythonRuntime(dir, targetKey) {
  // Drop bytecode caches and the stdlib test suite; neither is ever imported
  // at runtime and together they are roughly 60 MB.
  const removed = { pycache: 0, testDirs: 0 }
  const walk = (current) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === '__pycache__') {
          removeRecursiveIfExist(full)
          removed.pycache += 1
          continue
        }
        if (entry.name === 'test' && current === path.join(dir, 'lib', 'python3.11')) {
          removeRecursiveIfExist(full)
          removed.testDirs += 1
          continue
        }
        walk(full)
      } else if (entry.isFile() && /\.py[co]$/.test(entry.name)) {
        rmSync(full, { force: true })
      }
    }
  }
  walk(dir)
  const windowsLibTest = path.join(dir, 'Lib', 'test')
  if (isWindows(targetKey) && existsSync(windowsLibTest)) {
    removeRecursiveIfExist(windowsLibTest)
    removed.testDirs += 1
  }
  log(`瘦身完成: 移除 ${removed.pycache} 个 __pycache__、${removed.testDirs} 个 stdlib test 目录`)
}

function installDependencies(interpreter) {
  const lockFile = path.join(serverRoot, 'requirements.lock')
  if (!existsSync(lockFile)) fail(`未找到 ${lockFile}`)

  // uv installs straight into the PBS prefix (no venv, no pyvenv.cfg), which
  // keeps the tree relocatable.
  const uvAvailable = run('uv', ['--version'], { stdio: 'pipe' }).status === 0
  if (uvAvailable) {
    log('使用 uv 安装生产依赖')
    const result = run('uv', [
      'pip', 'install',
      '--python', interpreter,
      '--require-hashes',
      '-r', lockFile,
    ])
    if (result.status !== 0) fail('uv pip install 失败')
    return
  }

  log('uv 不可用,回退 pip(ensurepip)')
  let result = run(interpreter, ['-m', 'ensurepip', '--upgrade'])
  if (result.status !== 0) fail('ensurepip 失败')
  result = run(interpreter, [
    '-m', 'pip', 'install',
    '--no-warn-script-location',
    '--require-hashes',
    '-r', lockFile,
  ])
  if (result.status !== 0) fail('pip install 失败')
}

async function buildPythonRuntime(targetKey) {
  const asset = PBS_ASSETS[targetKey]
  const assetName = pbsAssetName(asset)
  const marker = {
    asset: assetName,
    sha256: asset.sha256,
    lockFile: 'server/requirements.lock',
  }
  const markerExists = existsSync(runtimeMarker)
  if (markerExists) {
    try {
      const current = JSON.parse(readFileSync(runtimeMarker, 'utf8'))
      if (current.asset === marker.asset && current.sha256 === marker.sha256) {
        const check = runInterpreter(pythonExecutable(pythonDir, targetKey), interpreterCheckCode(pythonDir))
        if (check.status === 0) {
          log(`python 运行时已是最新,跳过 (${assetName})`)
          return
        }
        log('现有 python 运行时自检失败,重新构建')
      }
    } catch {
      log('运行时标记损坏,重新构建')
    }
  }

  const tarball = path.join(cacheDir, assetName)
  await fetchVerified(pbsUrl(asset), tarball, asset.sha256)

  log(`解压 ${assetName} -> ${pythonDir}`)
  const stagingDir = path.join(buildDir, 'python-extract')
  removeRecursiveIfExist(stagingDir)
  removeRecursiveIfExist(pythonDir)
  mkdirSync(stagingDir, { recursive: true })
  extractPbs(tarball, stagingDir)
  // The archive contains a single top-level "python/" directory.
  const extractedRoot = path.join(stagingDir, 'python')
  if (!existsSync(extractedRoot)) fail('PBS 包布局异常: 未找到顶层 python/ 目录')
  copyTreeDereferenced(extractedRoot, pythonDir)
  removeRecursiveIfExist(stagingDir)

  const interpreter = pythonExecutable(pythonDir, targetKey)
  if (!existsSync(interpreter)) fail(`捆绑解释器不存在: ${interpreter}`)

  const prefixCheck = runInterpreter(interpreter, interpreterCheckCode(pythonDir))
  if (prefixCheck.status !== 0) {
    fail(`解释器自检失败: ${String(prefixCheck.stderr)}`)
  }
  log(`解释器自检通过: ${String(prefixCheck.stdout).trim()}`)

  installDependencies(interpreter)
  slimPythonRuntime(pythonDir, targetKey)

  // Relocation self-check: move the fully installed tree and confirm the
  // prefix still follows the interpreter. rename is cheap on the same volume.
  const relocated = path.join(buildDir, 'python-relocated')
  removeRecursiveIfExist(relocated)
  renameSync(pythonDir, relocated)
  try {
    const relocatedCheck = runInterpreter(pythonExecutable(relocated, targetKey), interpreterCheckCode(relocated))
    if (relocatedCheck.status !== 0) {
      fail(`relocation 自检失败: ${String(relocatedCheck.stderr)}`)
    }
    log(`relocation 自检通过: ${String(relocatedCheck.stdout).trim()}`)
  } finally {
    renameSync(relocated, pythonDir)
  }

  writeFileSync(runtimeMarker, `${JSON.stringify(marker, null, 2)}\n`)
}

// ---------------------------------------------------------------------------
// ffmpeg
// ---------------------------------------------------------------------------

async function buildFfmpeg(targetKey) {
  const asset = FFMPEG_ASSETS[targetKey]
  const targetName = isWindows(targetKey) ? 'ffmpeg.exe' : 'ffmpeg'
  const cached = path.join(cacheDir, asset.name)
  await fetchVerified(ffmpegUrl(asset), cached, asset.sha256)

  mkdirSync(binDir, { recursive: true })
  const target = path.join(binDir, targetName)
  copyFileSync(cached, target)
  chmodSync(target, 0o755)

  const version = run(target, ['-version'], { stdio: 'pipe' })
  if (version.status !== 0) fail(`捆绑 ffmpeg 无法执行: ${target}`)
  log(`ffmpeg 就绪: ${String(version.stdout).split('\n')[0]}`)
}

// ---------------------------------------------------------------------------
// Notices
// ---------------------------------------------------------------------------

function writeNotices() {
  const content = `# THIRD-PARTY NOTICES

This desktop bundle redistributes the following third-party artifacts.
Versions and sources are pinned in \`client/scripts/build-python-runtime.mjs\`.

## CPython (python-build-standalone)

- Artifact: cpython-${PBS_PYTHON_VERSION}+${PBS_RELEASE_TAG} (${PBS_VARIANT}), per-platform tarballs
- Source: https://github.com/astral-sh/python-build-standalone/releases/tag/${PBS_RELEASE_TAG}
- License: Python Software Foundation License Version 2
  (https://docs.python.org/3/license.html). Build tooling for
  python-build-standalone is MIT licensed.

## FFmpeg

- Artifact: ffmpeg-static ${FFMPEG_TAG} (FFmpeg ${FFMPEG_VERSION}), static single-file builds
- Source: https://github.com/eugeneware/ffmpeg-static/releases/tag/${FFMPEG_TAG}
  (macOS x64 builds originate from evermeet.cx; Windows/Linux builds from
  johnvansickle.com)
- License: GPL-2.0-or-later WITH GPL-3-0-or-later components (the builds
  include libx264 and other GPL libraries, which the application's video
  renderer requires). See https://ffmpeg.org/legal.html
- Full license texts are published alongside the upstream builds.

## Python packages

Production dependencies are installed from \`server/requirements.lock\`
(hash-pinned). Each package's license is stated in its metadata
(\`<dist-info>/LICENSE*\` inside \`resources/python/lib/python3.11/site-packages\`
or \`resources/python/Lib/site-packages\` on Windows).
`
  writeFileSync(path.join(buildDir, 'THIRD-PARTY-NOTICES.md'), content)
  log('已生成 THIRD-PARTY-NOTICES.md')
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const args = parseArgs(process.argv.slice(2))
const targetKey = resolveTargetKey(args)

if (args.clean) {
  log(`--clean: 删除 ${buildDir}`)
  removeRecursiveIfExist(buildDir)
}

mkdirSync(cacheDir, { recursive: true })
await buildPythonRuntime(targetKey)
await buildFfmpeg(targetKey)
writeNotices()

log(`完成: ${pythonDir}`)
log(`完成: ${path.join(binDir, isWindows(targetKey) ? 'ffmpeg.exe' : 'ffmpeg')}`)

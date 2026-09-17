/**
 * Verify root-relative documentation paths in repo-authored TypeScript. The
 * textual scan covers `docs/*.md` and `.agents/notes/*.md`, requires the
 * extension, checks matching string literals too, and excludes built
 * declarations and vendored source.
 */

import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { findReferenceViolations, uniqueRepoFiles, type ReferenceViolation as Violation } from './repo-files.ts'

const root = resolve(import.meta.dirname, '..')

/** Repo-authored TypeScript that may cite docs in comments. */
const PATTERNS = ['packages/**/*.ts', 'examples/**/*.ts']

/** Paths excluded from the scan: built output and vendored upstream source. */
const isExcluded = (p: string): boolean =>
  p.includes('/lib/') || p.endsWith('.d.ts') || p.startsWith('vendor/')

/** Root-relative Markdown path token, excluding trailing prose. */
const DOC_REF = /https?:\/\/[^\s)\]`]+|(?:\bdocs|\.agents\/notes)\/[A-Za-z0-9._/-]+\.md/g

/**
 * Find broken local references without treating external URL paths as local files.
 * @param root - Repository root for resolving local documentation.
 * @param absPath - Source file to inspect.
 * @returns Missing local references with source locations.
 */
export function findViolations(root: string, absPath: string): Violation[] {
  return findReferenceViolations(root, absPath, DOC_REF, ref => ref,
    ref => !/^https?:\/\//.test(ref) && !existsSync(resolve(root, ref)))
}

function main(): void {
  const files = uniqueRepoFiles(root, PATTERNS, isExcluded)
  const all = files.flatMap(file => findViolations(root, file.abs))
  const checked = files.length

  if (all.length === 0) {
    console.log(`verify-doc-refs: ${checked} file(s) checked, all documentation references resolve.`)
    process.exit(0)
  }

  console.error('verify-doc-refs: broken documentation references found in source comments (target does not exist):')
  for (const v of all) {
    console.error(`  ${v.file}:${v.line}  ${v.ref}`)
  }
  process.exit(1)
}

const entrypoint = process.argv[1]
if (entrypoint !== undefined && resolve(entrypoint) === fileURLToPath(import.meta.url)) main()

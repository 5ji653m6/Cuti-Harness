import { copyFileSync, existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Materialize root-relative tool configuration from its versioned source. */
export function materializeRootConfigs(root = resolve(dirname(fileURLToPath(import.meta.url)), '..')) {
  const sourceDirectory = join(root, 'config', 'root')
  for (const name of readdirSync(sourceDirectory)) {
    const source = join(sourceDirectory, name)
    const target = join(root, name)
    if (existsSync(target) && readFileSync(source).equals(readFileSync(target))) continue
    copyFileSync(source, target)
  }
}

materializeRootConfigs()

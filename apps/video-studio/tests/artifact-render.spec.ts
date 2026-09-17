import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../src/i18n/LanguageContext'
import { ArtifactDocument } from '../src/features/deep-agent-v2/ArtifactDocument'

afterEach(() => { vi.unstubAllGlobals() })

const renderDocument = (text: string, language: string) => {
  vi.stubGlobal('localStorage', { getItem: () => language })
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: [`/${language}/create`] },
    createElement(LanguageProvider, { children: createElement(ArtifactDocument, { children: text }) })))
}

describe('ArtifactDocument rendered output', () => {
  it('renders actual GFM table markup rather than pipe-separated paragraphs', () => {
    const html = renderDocument('## Continuity\n\n| Character | Clothing |\n| --- | --- |\n| Mina | Cream jacket |', 'en')
    expect(html).toContain('<table')
    expect(html).toContain('<th')
    expect(html).toContain('Cream jacket')
    expect(html).not.toContain('| --- |')
  })

  it.each(['zh', 'en'])('renders nested generated JSON safely in %s', (language) => {
    const html = renderDocument(JSON.stringify({ title: 'Test story', shots: [{ description: '<script>alert(1)</script>' }] }), language)
    expect(html).toContain('Test story')
    expect(html).toContain(language === 'zh' ? '镜头' : 'Shots')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('[object Object]')
  })
})

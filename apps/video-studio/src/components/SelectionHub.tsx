import { useState } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { useLanguage } from '@/i18n/LanguageContext'
import GenerationBox from '@/components/GenerationBox'

const HOME_SKILLS = [
  { id: 'short-drama-workflow', labelKey: 'homeSkillShortDrama' as const },
  { id: 'cuti-scenario-product-workflow', labelKey: 'homeSkillProductStory' as const },
  { id: 'cinematic', labelKey: 'homeSkillMovieTrailer' as const },
  { id: 'mv', labelKey: 'homeSkillMusicVideo' as const },
]

const SelectionHub = () => {
  const { t, language, setLanguage } = useLanguage()
  const navigate = useNavigate()
  const location = useLocation()
  const { lang: routeLang } = useParams<{ lang: string }>()
  const lang = routeLang || language || 'en'
  // nothing preselected: with no tag chosen the backend routes the request itself
  const [selectedSkillId, setSelectedSkillId] = useState('')
  const selectedSkill = HOME_SKILLS.find(skill => skill.id === selectedSkillId)

  const go = (path: string) => {
    navigate(`/${lang}${path}`)
  }

  const isCreate = !location.pathname.includes('/create')
    && !location.pathname.includes('/studio')
    && !location.pathname.includes('/video')

  return (
    <div className="home-landing relative min-h-screen overflow-hidden bg-black text-white antialiased">
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <div className="absolute inset-0 bg-black" />
        <img
          src="/home-hero-v8.jpg"
          alt=""
          className="home-planet-photo"
        />
      </div>

      <header className="home-header absolute inset-x-0 top-0 z-20 grid grid-cols-[1fr_auto_1fr] items-center">
        <button
          type="button"
          onClick={() => go('')}
          className="home-landing-hit home-logo justify-self-start"
        >
          Cuti
        </button>

        <nav className="home-nav justify-self-center flex items-center">
          {[
            { id: 'create', label: t('homeNavCreate'), path: '' },
            { id: 'chats', label: t('homeNavChats'), path: '/create' },
          ].map((item) => {
            const active = item.id === 'create' ? isCreate : false
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => go(item.path)}
                className={`home-landing-hit home-nav-item flex items-center justify-center ${
                  active ? 'home-nav-item-active' : ''
                }`}
              >
                {item.label}
              </button>
            )
          })}
        </nav>

        <button
          type="button"
          onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}
          className="home-landing-hit home-lang justify-self-end"
        >
          {language === 'en' ? 'EN' : '中文'}
        </button>
      </header>

      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center px-4">
        <div className="home-hero flex w-full flex-col items-center">
          <h1 className="home-headline text-center">
            {t('homeHeadline')}
          </h1>
          <p className="home-subhead text-center">
            {t('homeSubhead')}
          </p>

          <div className="home-composer-slot" data-generation-box>
            <GenerationBox
              variant="landing"
              placeholder={t('homePromptPlaceholder')}
              selectedWorkflowId={selectedSkillId || undefined}
              selectedWorkflowLabel={selectedSkill ? t(selectedSkill.labelKey) : undefined}
              onClearWorkflow={() => setSelectedSkillId('')}
            />
          </div>

          <div className="home-pills flex w-full flex-wrap items-center justify-center">
            {HOME_SKILLS.map((skill) => {
              const selected = selectedSkillId === skill.id
              return (
                <button
                  key={skill.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setSelectedSkillId(current => (current === skill.id ? '' : skill.id))}
                  className={selected ? 'home-skill-pill home-skill-pill-active' : 'home-skill-pill'}
                >
                  {t(skill.labelKey)}
                </button>
              )
            })}
          </div>
        </div>
      </main>
    </div>
  )
}

export default SelectionHub

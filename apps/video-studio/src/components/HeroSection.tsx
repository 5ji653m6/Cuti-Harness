import { useLanguage } from '@/i18n/LanguageContext'

const HeroSection = () => {
  const { language } = useLanguage()

  return (
    <div className="text-center mb-12 md:mb-20 lg:mb-24">
      <h1 className="animate-fade-in flex flex-col items-center justify-center max-w-5xl mx-auto px-1">
        <div className="flex flex-col items-center text-center gap-4 sm:gap-5 md:gap-6">
          <span className="font-space-grotesk text-xl sm:text-2xl md:text-3xl lg:text-4xl font-bold text-foreground leading-snug sm:leading-tight">
            Cuti.land
          </span>
          <span className="font-space-grotesk text-lg sm:text-2xl md:text-3xl font-light bg-gradient-to-r from-pink-500 via-purple-500 to-violet-600 bg-clip-text text-transparent">
            {language === 'zh'
              ? '让你的角色出演MV'
              : 'Create Music Videos with Your Characters'}
          </span>
        </div>
      </h1>
    </div>
  )
}

export default HeroSection

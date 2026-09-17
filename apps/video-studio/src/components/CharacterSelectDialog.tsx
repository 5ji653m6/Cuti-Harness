import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useState } from 'react'
import { toast } from 'sonner'
import characterCuti from '@/assets/character-cuti.png'
import characterDucky from '@/assets/character-ducky-BTL0N4lq.jpg'
import characterHana from '@/assets/character-human-hana-BtiGN0T0.png'
import characterJay from '@/assets/character-human-jay-o1ZEwgqU.png'
import characterLeo from '@/assets/character-human-leo-toLiEK8M.png'
import characterLuna from '@/assets/character-human-luna-CPe4KvLL.png'
import characterRuby from '@/assets/character-human-ruby-BDFXLu1L.png'
import characterMiuMiu from '@/assets/character-MiuMiu.png'
import { useLanguage } from '@/i18n/LanguageContext'

interface Character {
  id: string
  name: string
  image: string
  isDefault?: boolean
}

interface CharacterSelectPopoverProps {
  children: React.ReactNode
  onSelect: (characters: Character[]) => void
  selectedCharacters?: Character[]
}

const DEFAULT_CHARACTERS: Character[] = [
  { id: 'cuti', name: 'Cuti', image: characterCuti, isDefault: true },
  { id: 'miumiu', name: 'Mimi', image: characterMiuMiu, isDefault: true },
  { id: 'hana', name: 'Hana', image: characterHana, isDefault: true },
  { id: 'jay', name: 'Jay', image: characterJay, isDefault: true },
  { id: 'leo', name: 'Leo', image: characterLeo, isDefault: true },
  { id: 'luna', name: 'Luna', image: characterLuna, isDefault: true },
  { id: 'ruby', name: 'Ruby', image: characterRuby, isDefault: true },
  { id: 'ducky', name: 'Ducky', image: characterDucky, isDefault: true },
]

const CharacterSelectPopover = ({
  children,
  onSelect,
  selectedCharacters = [],
}: CharacterSelectPopoverProps) => {
  const { t } = useLanguage()
  const characters: Character[] = DEFAULT_CHARACTERS
  const [selected, setSelected] = useState<string[]>(
    selectedCharacters.map(c => c.id),
  )

  const toggleCharacter = (id: string, name: string) => {
    setSelected((prev) => {
      const newSelected = prev.includes(id)
        ? prev.filter(charId => charId !== id)
        : [...prev, id]

      // Auto-update selected characters
      const selectedChars = characters.filter(c => newSelected.includes(c.id))
      onSelect(selectedChars)

      // Show toast
      if (newSelected.includes(id)) {
        toast.success(`${name} ${t('characterSelected')}`)
      } else {
        toast.success(`${name} ${t('characterDeselected')}`)
      }

      return newSelected
    })
  }

  return (
    <>
      <Popover>
        <PopoverTrigger asChild>
          {children}
        </PopoverTrigger>
        <PopoverContent
          side="bottom"
          align="start"
          sideOffset={8}
          avoidCollisions={false}
          className="w-[calc(100vw-2rem)] max-w-[800px] bg-popover/95 backdrop-blur-xl border border-border z-50 p-4 rounded-2xl"
        >
          <div className="space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
              <h4 className="font-medium text-sm text-muted-foreground">
                {t('pickCharacter')}
              </h4>
            </div>

            {/* Characters Grid */}
            <div className="flex gap-3 overflow-x-auto pb-2">
              {characters.map((character) => {
                const isSelected = selected.includes(character.id)
                return (
                  <button
                    key={character.id}
                    onClick={() =>{  toggleCharacter(character.id, character.name) }}
                    className="flex-shrink-0 flex flex-col items-center gap-2 p-2 rounded-xl hover:bg-muted/50 transition-all group"
                  >
                    <div
                      className={`w-[130px] h-[130px] rounded-xl overflow-hidden border-2 group-hover:scale-105 transition-all duration-200 ${
                        isSelected
                          ? 'border-primary ring-2 ring-primary/30'
                          : 'border-border group-hover:border-primary/50'
                      }`}
                    >
                      <img
                        src={character.image}
                        alt={character.name}
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <span
                      className={`text-xs font-medium transition-colors ${
                        isSelected
                          ? 'text-primary'
                          : 'text-muted-foreground group-hover:text-foreground'
                      }`}
                    >
                      {character.name}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </>
  )
}

export default CharacterSelectPopover

import { Clapperboard, Mic2, Wand2 } from "lucide-react";
import { useTranslation } from "react-i18next";

export type SceneAudioMode = "model" | "tts" | null;

interface AudioModeToggleProps {
  /** 当前覆盖值：`null` = 沿用整集默认。 */
  value: SceneAudioMode;
  onChange: (value: SceneAudioMode) => void;
  disabled?: boolean;
}

const CHOICES: { value: SceneAudioMode; icon: typeof Wand2; labelKey: string }[] = [
  { value: null, icon: Wand2, labelKey: "audio_mode_default" },
  { value: "model", icon: Clapperboard, labelKey: "audio_mode_model" },
  { value: "tts", icon: Mic2, labelKey: "audio_mode_tts" },
];

/**
 * 分镜声音归属三态开关：默认（沿用整集设置）/ 模型原声 / 旁白配音。
 * 对应后端 `DramaScene.audio_mode` / `NarrationSegment.audio_mode`，经
 * `onUpdatePrompt` 落库（与 note / transition_to_next 同路径）。
 */
export function AudioModeToggle({ value, onChange, disabled }: AudioModeToggleProps) {
  const { t } = useTranslation("dashboard");
  return (
    <span
      role="group"
      aria-label={t("audio_mode_label")}
      className="inline-flex overflow-hidden rounded-md border border-[var(--color-hairline)]"
    >
      {CHOICES.map(({ value: choice, icon: Icon, labelKey }) => {
        const active = value === choice;
        return (
          <button
            key={choice ?? "default"}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            title={t(labelKey)}
            aria-label={t(labelKey)}
            onClick={() => onChange(choice)}
            className="focus-ring inline-flex items-center px-1.5 py-1 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              color: active ? "var(--color-accent-2)" : "var(--color-text-3)",
              background: active ? "var(--color-accent-dim)" : "oklch(0.22 0.011 265 / 0.5)",
            }}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        );
      })}
    </span>
  );
}

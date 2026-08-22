import { MAX_PERSONA_FIELD_LENGTH, type CharacterFormData } from "./types";

interface PersonalitySectionProps {
  formData: CharacterFormData;
  readOnly: boolean;
  onFieldChange: <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => void;
}

export function PersonalitySection({ formData, readOnly, onFieldChange }: PersonalitySectionProps) {
  return (
    <section className="char-create-card" data-testid="section-persona">
      <div className="char-create-section-head">
        <h2 className="char-create-section-title">人格设定</h2>
        <span className="char-create-meta">上限各 {MAX_PERSONA_FIELD_LENGTH} 字</span>
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-personality">
          性格
        </label>
        <textarea
          id="f-personality"
          className="char-create-textarea"
          maxLength={MAX_PERSONA_FIELD_LENGTH}
          placeholder="描述角色的性格、说话方式、价值观…"
          value={formData.personality}
          onChange={(e) => onFieldChange("personality", e.target.value)}
          disabled={readOnly}
        />
        <span className="char-create-char-count" data-testid="count-personality">
          {formData.personality.length} / {MAX_PERSONA_FIELD_LENGTH} 字
        </span>
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-scenario">
          对话场景
        </label>
        <textarea
          id="f-scenario"
          className="char-create-textarea"
          maxLength={MAX_PERSONA_FIELD_LENGTH}
          placeholder="故事发生的背景、时间、地点…"
          value={formData.scenario}
          onChange={(e) => onFieldChange("scenario", e.target.value)}
          disabled={readOnly}
        />
        <span className="char-create-char-count" data-testid="count-scenario">
          {formData.scenario.length} / {MAX_PERSONA_FIELD_LENGTH} 字
        </span>
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-first-msg">
          第一条消息
        </label>
        <textarea
          id="f-first-msg"
          className="char-create-textarea"
          maxLength={MAX_PERSONA_FIELD_LENGTH}
          placeholder="角色开场说的第一句话…"
          value={formData.first_mes}
          onChange={(e) => onFieldChange("first_mes", e.target.value)}
          disabled={readOnly}
        />
        <span className="char-create-char-count" data-testid="count-first-msg">
          {formData.first_mes.length} / {MAX_PERSONA_FIELD_LENGTH} 字
        </span>
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-example">
          示例对话
        </label>
        <textarea
          id="f-example"
          className="char-create-textarea"
          maxLength={MAX_PERSONA_FIELD_LENGTH}
          placeholder="一段示例对话，帮助模型把握语气…"
          value={formData.mes_example}
          onChange={(e) => onFieldChange("mes_example", e.target.value)}
          disabled={readOnly}
        />
        <span className="char-create-char-count" data-testid="count-example">
          {formData.mes_example.length} / {MAX_PERSONA_FIELD_LENGTH} 字
        </span>
      </div>
    </section>
  );
}

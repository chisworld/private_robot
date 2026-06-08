import { CubismModelSettingJson } from './cubismmodelsettingjson';
import { CubismDefaultParameterId } from './cubismdefaultparameterid';
import { CubismEyeBlink } from './effect/cubismeyeblink';
import { CubismBreath } from './effect/cubismbreath';
import { CubismUserModel } from './model/cubismusermodel';
import { CubismExpressionMotion } from './motion/cubismexpressionmotion';
import { CubismMotion } from './motion/cubismmotion';
import { CubismFramework } from './live2dcubismframework';
import { CubismTargetPoint } from './math/cubismtargetpoint';
import { ACubismMotion } from './motion/acubismmotion';

const DEFAULT_CANVAS_SIZE = 4096;

// ── 吸血姬 expression list ───────────────────────────────────────────────────
// Only expressions that exist on disk for 血裔少女.
// watermark.exp3.json is intentionally excluded to prevent watermark from
// appearing when the user clicks the character.

const DEFAULT_EXPRESSION_FILES: Array<{ name: string; file: string }> = [
  { name: '默认', file: 'Black.exp3.json' },
  { name: '脸红', file: 'blush.exp3.json' },
  { name: '哭', file: 'cry.exp3.json' },
  { name: '钱', file: 'money.exp3.json' },
  { name: '抱玩偶', file: 'Hold the doll.exp3.json' },
  { name: '灯笼', file: 'lantern.exp3.json' },
  { name: '话筒', file: 'microphone.exp3.json' },
  { name: '拿镰刀', file: 'Take a scythe.exp3.json' },
  { name: '拿杯子', file: 'Take the cup.exp3.json' },
  { name: '拿苹果', file: 'Take the apple.exp3.json' },
  { name: '刘海', file: 'bangs.exp3.json' },
  { name: '面纱', file: 'Veil.exp3.json' },
  { name: '头饰', file: 'headdress.exp3.json' },
  { name: '小熊', file: 'little bear.exp3.json' },
  { name: '红发', file: 'Redheads.exp3.json' },
  { name: '骨架', file: 'skeleton.exp3.json' },
  { name: '胸眼', file: 'Chest eyes.exp3.json' },
  { name: '裙爱心', file: 'Skirt love.exp3.json' },
  { name: '裙侧', file: 'Skirt side.exp3.json' },
  { name: '袖子', file: 'sleeves.exp3.json' },
  { name: '缩小', file: 'shrink.exp3.json' },
  { name: '镰刀', file: 'sickle.exp3.json' },
];

// ── Action items (exp3.json that toggle visible props) ──────────────────────
// These are expressions that toggle visible costume pieces / props.
// Excluded from this list: watermark, emotional expressions (blush/cry/etc.),
// and permanent-toggles (bangs/veil/headdress/skirt/sleeves/shrink/skeleton).
const ACTION_ITEM_FILES: Array<{ name: string; file: string }> = [
  { name: '抱玩偶', file: 'Hold the doll.exp3.json' },
  { name: '拿镰刀', file: 'Take a scythe.exp3.json' },
  { name: '拿杯子', file: 'Take the cup.exp3.json' },
  { name: '拿苹果', file: 'Take the apple.exp3.json' },
  { name: '拿话筒', file: 'microphone.exp3.json' },
  { name: '灯笼', file: 'lantern.exp3.json' },
  { name: '小熊', file: 'little bear.exp3.json' },
];

// ── Posture presets ──────────────────────────────────────────────────────────

export interface PostureParams {
  [paramId: string]: number;
}

export const POSTURE_STAND: PostureParams = {
  ParamBodyAngleX: 0.0,
  ParamBodyAngleY: 0.0,
  ParamBodyAngleZ: 0.0,
  ParamBaseY: 0.0,
};

export const POSTURE_SIT: PostureParams = {
  ParamBodyAngleX: 0.12,
  ParamBodyAngleY: 0.0,
  ParamBodyAngleZ: 0.0,
  ParamBaseY: -0.18,
};

export const POSTURE_CROUCH: PostureParams = {
  ParamBodyAngleX: 0.22,
  ParamBodyAngleY: 0.0,
  ParamBodyAngleZ: 0.0,
  ParamBaseY: -0.30,
};

export const POSTURE_NAMES: Record<string, string> = {
  stand: '站立',
  sit: '坐着',
  crouch: '蹲下',
};

export class LAppModel extends CubismUserModel {
  private _modelHomeDir: string = '';
  private _modelSetting: CubismModelSettingJson | null = null;
  private _expressionMotions: Map<string, ACubismMotion> = new Map();
  private _expressionNames: string[] = [];
  private _textureImages: Array<{ index: number; path: string; image: HTMLImageElement }> = [];

  // ── Motion playback state ──────────────────────────────────────────────────
  private _loadedMotions: Map<string, CubismMotion> = new Map();
  private _motionNames: string[] = [];
  private _motionSpeed: number = 1.0;
  private _motionDeltaAccumulator: number = 0.0;

  // ── Random action system ──────────────────────────────────────────────────
  // Action items are expressions (.exp3.json) that toggle visible props
  // (Hold the doll, Take a scythe, microphone, etc.). When triggered, we
  // activate the expression for actionDurationSeconds then deactivate it.
  private _actionItems: Array<{ name: string; motion: ACubismMotion }> = [];
  private _actionDurationSeconds: number = 3.0;
  private _activeAction: { name: string; motion: ACubismMotion; remaining: number } | null = null;
  private _randomActionTimerId: ReturnType<typeof setInterval> | null = null;
  private _randomActionMinInterval: number = 8;
  private _randomActionMaxInterval: number = 20;

  // ── Tap reaction (procedural) ─────────────────────────────────────────────
  private _tapReactionActive: boolean = false;
  private _tapReactionTime: number = 0;
  private _tapReactionDuration: number = 0.7;
  private static readonly _TAP_PARAM_AMPLITUDES: Record<string, number> = {
    ParamAngleX: 0.10,
    ParamAngleY: 0.06,
    ParamBodyAngleX: 0.06,
    ParamBodyAngleY: -0.04,
    ParamBodyAngleZ: 0.05,
    ParamBaseY: -0.06,
  };

  // ── Expression transition state ────────────────────────────────────────────
  private _expressionTransitionMs: number = 400;
  private _activeExpressionName: string | null = null;

  // ── Posture transition state ───────────────────────────────────────────────
  private _postureTransitionMs: number = 600;
  private _activePosture: string = 'stand';
  private _postureTransitionRemaining: number = 0;
  private _postureTransitionTotal: number = 0;
  private _fromPostureSnapshot: Map<string, { from: number; to: number }> | null = null;

  get modelSetting(): CubismModelSettingJson | null {
    return this._modelSetting;
  }

  get expressionNames(): string[] {
    return this._expressionNames;
  }

  get motionNames(): string[] {
    return this._motionNames;
  }

  get motionSpeed(): number {
    return this._motionSpeed;
  }

  set motionSpeed(v: number) {
    this._motionSpeed = Math.max(0.1, Math.min(3.0, v));
  }

  get expressionTransitionMs(): number {
    return this._expressionTransitionMs;
  }

  set expressionTransitionMs(ms: number) {
    this._expressionTransitionMs = Math.max(0, Math.min(3000, ms));
  }

  get postureTransitionMs(): number {
    return this._postureTransitionMs;
  }

  set postureTransitionMs(ms: number) {
    this._postureTransitionMs = Math.max(0, Math.min(3000, ms));
  }

  get activePosture(): string {
    return this._activePosture;
  }

  get actionDurationSeconds(): number {
    return this._actionDurationSeconds;
  }

  set actionDurationSeconds(s: number) {
    this._actionDurationSeconds = Math.max(1, Math.min(30, s));
  }

  get actionNames(): string[] {
    return this._actionItems.map(a => a.name);
  }

  async load(
    modelHomePath: string,
    expressionFiles?: Array<{ name: string; file: string }>
  ): Promise<void> {
    this._modelHomeDir = modelHomePath.endsWith('/')
      ? modelHomePath
      : modelHomePath + '/';

    // Load model3.json — auto-detect which model file exists
    const modelJsonCandidates = ['血裔少女.model3.json', '我也要死吗.model3.json'];
    let jsonName = '';
    let settingBuf: ArrayBuffer | null = null;

    for (const name of modelJsonCandidates) {
      try {
        const resp = await fetch(this._modelHomeDir + name);
        if (resp.ok) {
          jsonName = name;
          settingBuf = await resp.arrayBuffer();
          break;
        }
      } catch { /* try next */ }
    }

    if (!settingBuf) {
      throw new Error(
        `无法加载 model3.json（${modelJsonCandidates.join(', ')}）。` +
          '请运行 python scripts/sync_live2d_assets.py 同步模型资源。'
      );
    }

    this._modelSetting = new CubismModelSettingJson(settingBuf, settingBuf.byteLength);

    // Load moc3
    const mocName = this._modelSetting.getModelFileName();
    const mocResp = await fetch(this._modelHomeDir + mocName);
    if (!mocResp.ok) {
      throw new Error(
        `无法加载 ${mocName}（HTTP ${mocResp.status}）。` +
          '请运行 python scripts/sync_live2d_assets.py'
      );
    }
    const mocBuf = await mocResp.arrayBuffer();
    this.loadModel(mocBuf);
    if (!this.getModel()) throw new Error('Failed to load moc3');

    // Create renderer
    const w = this.getModel().getCanvasWidth() || DEFAULT_CANVAS_SIZE;
    const h = this.getModel().getCanvasHeight() || DEFAULT_CANVAS_SIZE;
    this.createRenderer(w, h);

    // Preload texture images (GL textures created after GL init)
    await this._preloadTextureImages();

    // Load physics
    await this._loadPhysics();

    // Load expressions — skip watermark.exp3.json
    const expressions = expressionFiles ?? DEFAULT_EXPRESSION_FILES;
    await this._loadExpressions(expressions);

    // Load action items (props that can be toggled on for a duration)
    await this._loadActionItems();

    // Load motion3.json for idle animation
    await this._discoverAndLoadMotions();

    // Play idle motion on loop if available
    this._startIdleMotion();

    // Start random action timer
    this._startRandomActionTimer();

    // Set up auto animations
    this._setupAutoAnimations();

    this.setInitialized(true);
  }

  /** Upload preloaded texture images to WebGL textures */
  setupTextures(gl: WebGLRenderingContext): void {
    const renderer = this.getRenderer();
    if (!renderer) return;

    for (const { index, image } of this._textureImages) {
      const texture = gl.createTexture();
      if (!texture) continue;
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.generateMipmap(gl.TEXTURE_2D);
      renderer.bindTexture(index, texture);
    }
    this._textureImages = [];
  }

  // ── Motion playback ──────────────────────────────────────────────────────────

  /** Trigger a visible tap-reaction animation (procedural, ~0.7s) + random action */
  triggerTapReaction(): void {
    // Procedural bounce
    this._tapReactionActive = true;
    this._tapReactionTime = 0;
    // Also trigger a random action
    this._triggerRandomAction();
  }

  /** Manually trigger a named action for actionDurationSeconds */
  playAction(actionName?: string): boolean {
    const items = this._actionItems;
    if (items.length === 0) return false;

    let item: { name: string; motion: ACubismMotion } | undefined;
    if (actionName) {
      item = items.find(a => a.name === actionName);
    } else {
      // Pick random
      item = items[Math.floor(Math.random() * items.length)];
    }

    if (!item) {
      console.warn('Action not found:', actionName ?? '(none)');
      return false;
    }

    this._activateActionItem(item);
    return true;
  }

  private _triggerRandomAction(): void {
    if (this._actionItems.length === 0) return;
    const item = this._actionItems[Math.floor(Math.random() * this._actionItems.length)];
    this._activateActionItem(item);
  }

  private _activateActionItem(item: { name: string; motion: ACubismMotion }): void {
    // Activate expression
    if (this._expressionManager) {
      item.motion.setFadeInTime(0.15);
      this._expressionManager.startMotion(item.motion, false);
    }
    this._activeAction = { ...item, remaining: this._actionDurationSeconds };
  }

  private _deactivateActionItem(): void {
    this._activeAction = null;
  }

  private _startRandomActionTimer(): void {
    if (this._randomActionTimerId) return;
    this._scheduleNextRandomAction();
  }

  private _scheduleNextRandomAction(): void {
    if (this._randomActionTimerId) clearTimeout(this._randomActionTimerId);
    const delay = this._randomActionMinInterval +
      Math.random() * (this._randomActionMaxInterval - this._randomActionMinInterval);
    this._randomActionTimerId = setTimeout(() => {
      this._triggerRandomAction();
      this._scheduleNextRandomAction();
    }, delay * 1000);
  }

  stopRandomActions(): void {
    if (this._randomActionTimerId) {
      clearTimeout(this._randomActionTimerId);
      this._randomActionTimerId = null;
    }
    this._deactivateActionItem();
  }

  setRandomActionInterval(minSec: number, maxSec: number): void {
    this._randomActionMinInterval = Math.max(2, minSec);
    this._randomActionMaxInterval = Math.max(this._randomActionMinInterval + 2, maxSec);
    // Reschedule
    if (this._randomActionTimerId) {
      clearTimeout(this._randomActionTimerId);
      this._randomActionTimerId = null;
      this._scheduleNextRandomAction();
    }
  }

  // ── Action item loading ──────────────────────────────────────────────────────

  private async _loadActionItems(): Promise<void> {
    for (const act of ACTION_ITEM_FILES) {
      try {
        const resp = await fetch(this._modelHomeDir + act.file);
        if (!resp.ok) continue;
        const buf = await resp.arrayBuffer();
        const motion = CubismExpressionMotion.create(buf, buf.byteLength);
        if (motion) {
          this._actionItems.push({ name: act.name, motion });
        }
      } catch {
        console.warn('Failed to load action item:', act.name);
      }
    }
  }

  playMotion(motionName?: string): boolean {
    if (!this._motionManager) return false;

    let motion: CubismMotion | undefined;
    if (motionName) {
      motion = this._loadedMotions.get(motionName);
    } else {
      const nonIdle = this._motionNames.filter(n => n !== 'idle');
      const name = nonIdle[0] ?? this._motionNames[0];
      if (name) motion = this._loadedMotions.get(name);
    }

    if (!motion) {
      console.warn('Motion not found:', motionName ?? '(none)');
      return false;
    }

    motion.setLoop(false);
    motion.setFadeInTime(0.15);
    motion.setFadeOutTime(0.2);
    this._motionManager.startMotionPriority(motion, false, 1);
    this._motionDeltaAccumulator = 0;
    return true;
  }

  stopMotion(): void {
    if (this._motionManager) {
      this._motionManager.stopAllMotions();
    }
    this._motionDeltaAccumulator = 0;
    this._startIdleMotion();
  }

  private _startIdleMotion(): void {
    const idle = this._loadedMotions.get('idle');
    if (idle && this._motionManager) {
      idle.setLoop(true);
      idle.setLoopFadeIn(true);
      idle.setFadeInTime(0.8);
      idle.setFadeOutTime(0.3);
      this._motionManager.startMotionPriority(idle, false, 0);
    }
  }

  private async _discoverAndLoadMotions(): Promise<void> {
    const knownMotions = [
      { name: 'idle', file: 'Scene1.motion3.json' },
    ];

    for (const m of knownMotions) {
      try {
        const resp = await fetch(this._modelHomeDir + m.file);
        if (!resp.ok) continue;
        const buf = await resp.arrayBuffer();
        const motion = this.loadMotion(buf, buf.byteLength, m.name);
        if (motion) {
          this._loadedMotions.set(m.name, motion);
          this._motionNames.push(m.name);
        }
      } catch {
        // Motion file not found — that's okay
      }
    }
  }

  // ── Private helpers ───────────────────────────────────────────────────────────

  private async _preloadTextureImages(): Promise<void> {
    if (!this._modelSetting) return;
    const textureCount = this._modelSetting.getTextureCount();
    for (let i = 0; i < textureCount; i++) {
      const texPath = this._modelSetting.getTextureFileName(i);
      const img = await this._loadImage(this._modelHomeDir + texPath);
      this._textureImages.push({ index: i, path: texPath, image: img });
    }
  }

  private _loadImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    });
  }

  private async _loadPhysics(): Promise<void> {
    if (!this._modelSetting) return;
    const physicsName = this._modelSetting.getPhysicsFileName();
    if (!physicsName) return;

    const resp = await fetch(this._modelHomeDir + physicsName);
    const buf = await resp.arrayBuffer();
    this.loadPhysics(buf, buf.byteLength);
  }

  private async _loadExpressions(
    exprList: Array<{ name: string; file: string }>
  ): Promise<void> {
    for (const exp of exprList) {
      try {
        const resp = await fetch(this._modelHomeDir + exp.file);
        const buf = await resp.arrayBuffer();
        const motion = CubismExpressionMotion.create(buf, buf.byteLength);
        if (motion) {
          this._expressionMotions.set(exp.name, motion);
          this._expressionNames.push(exp.name);
        }
      } catch {
        console.warn('Failed to load expression:', exp.name);
      }
    }
  }

  private _setupAutoAnimations(): void {
    if (!this._eyeBlink && this._modelSetting) {
      this._eyeBlink = CubismEyeBlink.create(this._modelSetting);
    }

    if (!this._dragManager) {
      this._dragManager = new CubismTargetPoint();
    }
  }

  // ── Public controls ───────────────────────────────────────────────────────────

  setExpression(expressionName: string): void {
    const motion = this._expressionMotions.get(expressionName);
    if (!motion) return;

    if (this._expressionManager) {
      if (this._expressionTransitionMs > 0) {
        motion.setFadeInTime(this._expressionTransitionMs / 1000);
      }
      this._expressionManager.startMotion(motion, false);
    }
    this._activeExpressionName = expressionName;
  }

  setLipSync(value: number): void {
    const model = this.getModel();
    if (!model) return;
    const v = Math.max(0, Math.min(1, value));
    model.setParameterValueById(
      CubismFramework.getIdManager().getId(CubismDefaultParameterId.ParamMouthOpenY),
      v
    );
    model.setParameterValueById(
      CubismFramework.getIdManager().getId(CubismDefaultParameterId.ParamMouthForm),
      v * 0.5
    );
  }

  setParameter(id: string, value: number, weight: number = 1.0): void {
    const model = this.getModel();
    if (!model) return;
    model.setParameterValueById(
      CubismFramework.getIdManager().getId(id),
      value,
      weight
    );
  }

  getParameter(id: string): number {
    const model = this.getModel();
    if (!model) return 0;
    return model.getParameterValueById(CubismFramework.getIdManager().getId(id));
  }

  // ── Posture control ───────────────────────────────────────────────────────────

  setPosture(postureName: string): void {
    const presets: Record<string, PostureParams> = {
      stand: POSTURE_STAND,
      sit: POSTURE_SIT,
      crouch: POSTURE_CROUCH,
    };

    const target = presets[postureName];
    if (!target) {
      console.warn('Unknown posture:', postureName);
      return;
    }

    if (this._postureTransitionMs <= 0) {
      for (const [id, value] of Object.entries(target)) {
        this.setParameter(id, value);
      }
      this._activePosture = postureName;
      return;
    }

    this._fromPostureSnapshot = new Map();
    for (const [id, to] of Object.entries(target)) {
      const from = this.getParameter(id);
      this._fromPostureSnapshot.set(id, { from, to });
    }
    this._postureTransitionRemaining = this._postureTransitionMs / 1000;
    this._postureTransitionTotal = this._postureTransitionMs / 1000;
    this._activePosture = postureName;
  }

  // ── Update ────────────────────────────────────────────────────────────────────

  update(deltaSeconds: number): void {
    if (!this.isInitialized()) return;

    const model = this.getModel();
    if (!model) return;

    const effectiveDelta = deltaSeconds * this._motionSpeed;

    if (this._dragManager) {
      this._dragManager.update(effectiveDelta);
    }

    if (this._physics) {
      this._physics.evaluate(model, effectiveDelta);
    }

    if (this._pose) {
      this._pose.updateParameters(model, effectiveDelta);
    }

    if (this._eyeBlink) {
      this._eyeBlink.updateParameters(model, effectiveDelta);
    }

    // Motion playback (idle + user-triggered)
    if (this._motionManager) {
      this._motionManager.updateMotion(model, effectiveDelta);
    }

    // Expression updates
    if (this._expressionManager) {
      this._expressionManager.updateMotion(model, effectiveDelta);
    }

    if (this._breath && this._breath.getParameters().length > 0) {
      this._breath.updateParameters(model, effectiveDelta);
    }

    // Posture transition interpolation
    if (this._postureTransitionRemaining > 0 && this._fromPostureSnapshot) {
      const progress = 1.0 - (this._postureTransitionRemaining / this._postureTransitionTotal);
      const t = progress < 0.5
        ? 2 * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 2) / 2;

      for (const [id, { from, to }] of this._fromPostureSnapshot.entries()) {
        const value = from + (to - from) * t;
        this.setParameter(id, value, 1.0);
      }

      this._postureTransitionRemaining -= deltaSeconds;
      if (this._postureTransitionRemaining <= 0) {
        for (const [id, { to }] of this._fromPostureSnapshot.entries()) {
          this.setParameter(id, to, 1.0);
        }
        this._fromPostureSnapshot = null;
      }
    }

    // ── Tap reaction interpolation ───────────────────────────────────────────
    if (this._tapReactionActive) {
      this._tapReactionTime += effectiveDelta;
      const t = this._tapReactionTime / this._tapReactionDuration;
      if (t >= 1.0) {
        for (const id of Object.keys(LAppModel._TAP_PARAM_AMPLITUDES)) {
          this.setParameter(id, 0, 0.3);
        }
        this._tapReactionActive = false;
        this._tapReactionTime = 0;
      } else {
        const phase = t * Math.PI;
        const decay = 1.0 - t;
        const amplitude = Math.sin(phase) * decay;
        for (const [id, maxAmp] of Object.entries(LAppModel._TAP_PARAM_AMPLITUDES)) {
          this.setParameter(id, amplitude * maxAmp, 0.6);
        }
      }
    }

    // ── Action item timer (auto-deactivate after duration) ──────────────────
    if (this._activeAction) {
      this._activeAction.remaining -= effectiveDelta;
      if (this._activeAction.remaining <= 0) {
        // Deactivate: start the same expression again to toggle it off
        // (Expressions are toggles — starting them again turns them off)
        if (this._expressionManager) {
          this._activeAction.motion.setFadeInTime(0.15);
          this._expressionManager.startMotion(this._activeAction.motion, false);
        }
        this._activeAction = null;
      }
    }

    // ── Force watermark OFF every frame ──────────────────────────────────────
    this.setParameter('Param24', 0, 1.0);

    model.update();
  }

  /** Clean up timers on destroy */
  release(): void {
    this.stopRandomActions();
    super.release();
  }
}

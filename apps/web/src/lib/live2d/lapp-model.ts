import { CubismModelSettingJson } from './cubismmodelsettingjson';
import { CubismDefaultParameterId } from './cubismdefaultparameterid';
import { CubismEyeBlink } from './effect/cubismeyeblink';
import { CubismBreath } from './effect/cubismbreath';
import { CubismUserModel } from './model/cubismusermodel';
import { CubismExpressionMotion } from './motion/cubismexpressionmotion';
import { CubismFramework } from './live2dcubismframework';
import { CubismTargetPoint } from './math/cubismtargetpoint';
import { ACubismMotion } from './motion/acubismmotion';

const DEFAULT_CANVAS_SIZE = 2048;

const DEFAULT_EXPRESSION_FILES: Array<{ name: string; file: string }> = [
  { name: '我也要死吗', file: '我也要死吗.exp3.json' },
  { name: '笑嘻', file: '笑嘻.exp3.json' },
  { name: '爱心眼', file: '爱心眼.exp3.json' },
  { name: '生气眉毛', file: '生气眉毛.exp3.json' },
  { name: '晕晕眼', file: '晕晕眼.exp3.json' },
  { name: '歪嘴', file: '歪嘴.exp3.json' },
  { name: '脸红', file: '脸红.exp3.json' },
  { name: '流汗', file: '流汗.exp3.json' },
  { name: '黑脸', file: '黑脸.exp3.json' },
  { name: '眼泪1', file: '眼泪1.exp3.json' },
  { name: '眼泪2', file: '眼泪2.exp3.json' },
  { name: '比耶', file: '比耶.exp3.json' },
  { name: 'X嘴', file: 'X嘴.exp3.json' },
  { name: '吐舌嘴', file: '吐舌嘴.exp3.json' },
  { name: '口水', file: '口水.exp3.json' },
  { name: '颤抖嘴', file: '颤抖嘴.exp3.json' },
  { name: '黑眼圈', file: '黑眼圈.exp3.json' },
  { name: '组合1 生气', file: '组合1 生气.exp3.json' },
  { name: '组合2 爱心', file: '组合2 爱心.exp3.json' },
  { name: '组合3 晕晕', file: '组合3 晕晕.exp3.json' },
  { name: '组合4 比耶晕晕', file: '组合4 比耶晕晕.exp3.json' },
  { name: '组合5', file: '组合5.exp3.json' },
];

export class LAppModel extends CubismUserModel {
  private _modelHomeDir: string = '';
  private _modelSetting: CubismModelSettingJson | null = null;
  private _expressionMotions: Map<string, ACubismMotion> = new Map();
  private _expressionNames: string[] = [];
  // Images preloaded before GL context is ready; uploaded to GL on setupTextures()
  private _textureImages: Array<{ index: number; path: string; image: HTMLImageElement }> = [];

  get modelSetting(): CubismModelSettingJson | null {
    return this._modelSetting;
  }

  get expressionNames(): string[] {
    return this._expressionNames;
  }

  async load(
    modelHomePath: string,
    expressionFiles?: Array<{ name: string; file: string }>
  ): Promise<void> {
    this._modelHomeDir = modelHomePath.endsWith('/')
      ? modelHomePath
      : modelHomePath + '/';

    // Load model3.json
    const jsonName = '我也要死吗.model3.json';
    const settingResp = await fetch(this._modelHomeDir + jsonName);
    if (!settingResp.ok) {
      throw new Error(
        `无法加载 ${jsonName}（HTTP ${settingResp.status}）。` +
          '请运行 python scripts/sync_live2d_assets.py 同步 14酱 模型资源。'
      );
    }
    const settingBuf = await settingResp.arrayBuffer();
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

    // Load expressions
    const expressions = expressionFiles ?? DEFAULT_EXPRESSION_FILES;
    await this._loadExpressions(expressions);

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

    // Breath not configured; skip to avoid uninitialized parameter crash

    if (!this._dragManager) {
      this._dragManager = new CubismTargetPoint();
    }
  }

  setExpression(expressionName: string): void {
    const motion = this._expressionMotions.get(expressionName);
    if (motion && this._expressionManager) {
      this._expressionManager.startMotion(motion, false);
    }
  }

  setLipSync(value: number): void {
    const model = this.getModel();
    if (!model) return;
    const v = Math.max(0, Math.min(1, value));
    model.setParameterValueById(
      CubismFramework.getIdManager().getId(CubismDefaultParameterId.ParamMouthOpenY),
      v
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

  update(deltaSeconds: number): void {
    if (!this.isInitialized()) return;

    const model = this.getModel();
    if (!model) return;

    if (this._dragManager) {
      this._dragManager.update(deltaSeconds);
    }

    if (this._physics) {
      this._physics.evaluate(model, deltaSeconds);
    }

    if (this._pose) {
      this._pose.updateParameters(model, deltaSeconds);
    }

    if (this._eyeBlink) {
      this._eyeBlink.updateParameters(model, deltaSeconds);
    }

    if (this._expressionManager) {
      this._expressionManager.updateMotion(model, deltaSeconds);
    }

    if (this._breath && this._breath.getParameters().length > 0) {
      this._breath.updateParameters(model, deltaSeconds);
    }

    model.update();
  }
}

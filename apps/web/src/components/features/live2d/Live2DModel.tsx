'use client';

import React, {
  useEffect,
  useRef,
  useImperativeHandle,
  forwardRef,
  useCallback,
  useState,
} from 'react';

import { CubismFramework, Option as CsmOption, LogLevel } from '@/lib/live2d/live2dcubismframework';
import { CubismRenderer_WebGL } from '@/lib/live2d/rendering/cubismrenderer_webgl';
import { CubismShaderManager_WebGL } from '@/lib/live2d/rendering/cubismshader_webgl';
import { LAppModel, POSTURE_NAMES } from '@/lib/live2d/lapp-model';

// Global init guard
let s_frameworkInitialized = false;

export interface Live2DModelHandle {
  setExpression: (name: string) => void;
  setLipSync: (value: number) => void;
  setParameter: (id: string, value: number) => void;
  getExpressionNames: () => string[];
  /** Play a motion3.json animation by name. If no name, plays the first available. */
  playMotion: (name?: string) => boolean;
  /** Stop all currently playing motions */
  stopMotion: () => void;
  /** Set motion playback speed (0.1 – 3.0, default 1.0) */
  setMotionSpeed: (speed: number) => void;
  /** Get current motion speed */
  getMotionSpeed: () => number;
  /** Get available motion names */
  getMotionNames: () => string[];
  /** Set expression transition duration in ms (0 = instant) */
  setExpressionTransitionMs: (ms: number) => void;
  /** Set posture: 'stand', 'sit', 'crouch' */
  setPosture: (name: string) => void;
  /** Get current posture name */
  getPosture: () => string;
  /** Get available posture names */
  getPostureNames: () => Record<string, string>;
  /** Trigger tap reaction (visible ~0.7s procedural animation) */
  triggerTapReaction: () => void;
  /** Play a random action item (prop toggle like "抱玩偶" etc.) for the configured duration */
  playAction: (name?: string) => void;
  /** Set action duration in seconds (default 3.0, range 1-30) */
  setActionDuration: (seconds: number) => void;
  /** Get configured action duration */
  getActionDuration: () => number;
  /** Get available action item names */
  getActionNames: () => string[];
  /** Set motion playback speed */
  hitTest: (x: number, y: number) => boolean;
}

interface Live2DModelProps {
  modelPath: string;
  width?: number;
  height?: number;
  className?: string;
  style?: React.CSSProperties;
  scale?: number;
  xOffset?: number;
  yOffset?: number;
  lipSyncValue?: number;
  activeExpression?: string;
  onLoad?: () => void;
  onError?: (error: Error) => void;
}

const Live2DModel = forwardRef<Live2DModelHandle, Live2DModelProps>(
  function Live2DModel(props, ref) {
    const {
      modelPath,
      width = 400,
      height = 600,
      className,
      style,
      scale = 1.0,
      xOffset = 0,
      yOffset = 0,
      lipSyncValue,
      activeExpression,
      onLoad,
      onError,
    } = props;

    const canvasRef = useRef<HTMLCanvasElement>(null);
    const modelRef = useRef<LAppModel | null>(null);
    const rafRef = useRef<number>(0);
    const lastTimeRef = useRef<number>(0);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Expose controls
    useImperativeHandle(ref, () => ({
      setExpression(name: string) {
        modelRef.current?.setExpression(name);
      },
      setLipSync(value: number) {
        modelRef.current?.setLipSync(value);
      },
      setParameter(id: string, value: number) {
        modelRef.current?.setParameter(id, value);
      },
      getExpressionNames() {
        return modelRef.current?.expressionNames ?? [];
      },
      playMotion(name?: string) {
        return modelRef.current?.playMotion(name) ?? false;
      },
      stopMotion() {
        modelRef.current?.stopMotion();
      },
      setMotionSpeed(speed: number) {
        if (modelRef.current) modelRef.current.motionSpeed = speed;
      },
      getMotionSpeed() {
        return modelRef.current?.motionSpeed ?? 1.0;
      },
      getMotionNames() {
        return modelRef.current?.motionNames ?? [];
      },
      setExpressionTransitionMs(ms: number) {
        if (modelRef.current) modelRef.current.expressionTransitionMs = ms;
      },
      setPosture(name: string) {
        modelRef.current?.setPosture(name);
      },
      getPosture() {
        return modelRef.current?.activePosture ?? 'stand';
      },
      getPostureNames() {
        return POSTURE_NAMES;
      },
      triggerTapReaction() {
        modelRef.current?.triggerTapReaction();
      },
      playAction(name?: string) {
        if (modelRef.current) modelRef.current.playAction(name);
      },
      setActionDuration(seconds: number) {
        if (modelRef.current) modelRef.current.actionDurationSeconds = seconds;
      },
      getActionDuration() {
        return modelRef.current?.actionDurationSeconds ?? 3;
      },
      getActionNames() {
        return modelRef.current?.actionNames ?? [];
      },
      hitTest(x: number, y: number) {
        return false;
      },
    }));

    // Initialize framework once
    const initFramework = useCallback(() => {
      if (s_frameworkInitialized) return;
      CubismFramework.startUp({
        logFunction: console.log,
        loggingLevel: LogLevel.LogLevel_Warning,
      } as CsmOption);
      CubismFramework.initialize();
      s_frameworkInitialized = true;
    }, []);

    // Render loop
    const renderLoop = useCallback((timestamp: number) => {
      const model = modelRef.current;
      const canvas = canvasRef.current;
      if (!model || !canvas) return;

      const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true });
      if (!gl) return;

      if (lastTimeRef.current === 0) {
        lastTimeRef.current = timestamp;
      }
      const delta = Math.min((timestamp - lastTimeRef.current) / 1000, 0.1);
      lastTimeRef.current = timestamp;

      // Clear
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      // Scale & offset
      const renderer = model.getRenderer();
      if (renderer) {
        const modelMatrix = model.getModelMatrix();
        if (modelMatrix) {
          modelMatrix.setWidth(canvas.width / scale);
          modelMatrix.setHeight(canvas.height / scale);
          modelMatrix.setX(xOffset * canvas.width / 2);
          modelMatrix.setY(yOffset * canvas.height / 2);
        }
      }

      // Update model
      model.update(delta);

      // Draw
      if (renderer) {
        renderer.drawModel();
      }

      rafRef.current = requestAnimationFrame(renderLoop);
    }, [scale, xOffset, yOffset]);

    // Load model on mount
    useEffect(() => {
      initFramework();

      const canvas = canvasRef.current;
      if (!canvas) return;

      let disposed = false;

      async function loadModel() {
        try {
          // Resize canvas for HiDPI
          const dpr = window.devicePixelRatio || 1;
          canvas!.width = width * dpr;
          canvas!.height = height * dpr;
          canvas!.style.width = width + 'px';
          canvas!.style.height = height + 'px';

          const gl = canvas!.getContext('webgl', {
            alpha: true,
            premultipliedAlpha: true,
          });
          if (!gl) throw new Error('WebGL not supported');

          // Create model and load assets
          const model = new LAppModel();
          // Set default transition times for smoother animations
          model.expressionTransitionMs = 400;
          model.postureTransitionMs = 600;
          await model.load(modelPath);

          // Initialize renderer with GL context for rendering
          const renderer = model.getRenderer() as CubismRenderer_WebGL;
          if (renderer) {
            renderer.startUp(gl);
          }

          // Set shader path and trigger async shader loading
          const shaderManager = CubismShaderManager_WebGL.getInstance();
          const shader = shaderManager.getShader(gl);
          if (shader) {
            shader.setShaderPath('/live2d/shaders/');
            shader.generateShaders();
          }

          // Upload preloaded texture images to WebGL
          if (gl) {
            model.setupTextures(gl);
          }

          if (disposed) {
            model.release();
            return;
          }

          modelRef.current = model;
          setLoaded(true);
          onLoad?.();

          // Wait for shader compilation before starting render loop
          await new Promise<void>((resolve) => {
            const check = () => {
              if (shader?._isShaderLoaded) {
                resolve();
              } else {
                setTimeout(check, 50);
              }
            };
            check();
          });

          // Start render loop
          lastTimeRef.current = 0;
          rafRef.current = requestAnimationFrame(renderLoop);
        } catch (err) {
          if (!disposed) {
            const msg = err instanceof Error ? err.message : String(err);
            setError(msg);
            onError?.(err instanceof Error ? err : new Error(msg));
          }
        }
      }

      loadModel();

      return () => {
        disposed = true;
        cancelAnimationFrame(rafRef.current);
        if (modelRef.current) {
          modelRef.current.release();
          modelRef.current = null;
        }
      };
    }, [modelPath, width, height]); // eslint-disable-line react-hooks/exhaustive-deps

    // React to lipSyncValue changes
    useEffect(() => {
      if (lipSyncValue !== undefined && modelRef.current) {
        modelRef.current.setLipSync(lipSyncValue);
      }
    }, [lipSyncValue]);

    // React to activeExpression changes
    useEffect(() => {
      if (activeExpression && modelRef.current) {
        modelRef.current.setExpression(activeExpression);
      }
    }, [activeExpression]);

    // Handle resize
    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas || !loaded) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
    }, [width, height, loaded]);

    return (
      <div className={className} style={{ position: 'relative', ...style }}>
        <canvas
          ref={canvasRef}
          style={{ display: 'block', width: width, height: height }}
        />
        {error && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#f87171',
              fontSize: '12px',
              textAlign: 'center',
              padding: '16px',
            }}
          >
            {error}
          </div>
        )}
      </div>
    );
  }
);

export default Live2DModel;

'use strict';

// Decorative instrument visuals. Every state they show is also present as text in the page.
(() => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const scenes = [];
  let colors = {};
  let frame = 0;
  let last = 0;

  function generator(seed) {
    return () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function readColors() {
    const style = getComputedStyle(document.body);
    const value = (name) => style.getPropertyValue(name).trim();
    colors = { ink: value('--ink'), graphite: value('--graphite'), signal: value('--signal'), bad: value('--bad'), rain: value('--rain') };
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = value('--page');
  }
  function fit(canvas) {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
  }

  // Agent proposals fall onto the authority boundary. Most stop there; a few pass as authorized.
  function boundaryScene(canvas) {
    const random = generator(11);
    const fallBelow = 150;
    let streaks = [];
    let impacts = [];
    let layoutKey = '';
    const spawn = (x, y) => ({ x, y, length: 28 + random() * 84, speed: 34 + random() * 76, passes: random() < 0.12 });
    function layout(width, boundary) {
      const key = `${width}:${boundary}`;
      if (key === layoutKey) return;
      layoutKey = key;
      const gap = width < 600 ? 18 : 26;
      streaks = [];
      for (let x = gap / 2; x < width; x += gap) streaks.push(spawn(Math.round(x + (random() - 0.5) * 8) + 0.5, random() * (boundary + fallBelow)));
    }
    function line(ctx, x, from, to) {
      if (to <= from) return;
      ctx.beginPath();
      ctx.moveTo(x, from);
      ctx.lineTo(x, to);
      ctx.stroke();
    }
    return {
      canvas,
      draw(_time, delta) {
        const { ctx, width, height } = fit(canvas);
        if (!width || !height) return;
        const boundary = parseFloat(getComputedStyle(canvas.parentElement).getPropertyValue('--boundary')) || height * 0.4;
        layout(width, boundary);
        ctx.lineWidth = 1;
        for (const streak of streaks) {
          streak.y += streak.speed * delta;
          const tail = streak.y - streak.length;
          if (!streak.passes && tail >= boundary) {
            impacts.push({ x: streak.x, age: 0 });
            Object.assign(streak, spawn(streak.x, -random() * boundary * 0.5));
            continue;
          }
          if (streak.passes && tail >= boundary + fallBelow) {
            Object.assign(streak, spawn(streak.x, -random() * boundary * 0.5));
            continue;
          }
          const fadeIn = Math.min(1, Math.max(0, streak.y) / 90);
          ctx.strokeStyle = `rgba(${colors.rain},${0.1 + 0.3 * fadeIn})`;
          line(ctx, streak.x, Math.max(0, tail), Math.min(streak.y, boundary));
          if (streak.passes && streak.y > boundary) {
            ctx.globalAlpha = Math.max(0, 1 - (streak.y - boundary) / fallBelow);
            ctx.strokeStyle = colors.signal;
            line(ctx, streak.x, Math.max(tail, boundary), streak.y);
            ctx.globalAlpha = 1;
          }
        }
        ctx.fillStyle = colors.ink;
        impacts = impacts.filter((impact) => (impact.age += delta) < 0.7);
        for (const impact of impacts) {
          ctx.globalAlpha = 1 - impact.age / 0.7;
          ctx.fillRect(impact.x - 6, boundary - 3, 12, 3);
        }
        ctx.globalAlpha = 1;
        ctx.fillRect(0, boundary, width, 1);
        ctx.fillStyle = colors.graphite;
        for (let x = 0; x < width; x += 8) ctx.fillRect(x, boundary + 1, 1, x % 40 === 0 ? 9 : 4);
      },
    };
  }

  // The Pegasus mark as a dithered dot-matrix solid. Its assembly follows the verified order state.
  const outline = [[-0.5, -0.55], [0.5, -0.55], [0.36, 0.29], [0, 0.55], [-0.36, 0.29]];
  const bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const shieldStates = {
    idle: { assembly: 0.93, tone: 'graphite', level: 0.85 },
    AWAITING_PAYMENT: { assembly: 0.66, tone: 'ink', level: 0.7 },
    CONFIRMED: { assembly: 1, tone: 'signal', level: 1 },
    REDEEMED: { assembly: 1, tone: 'ink', level: 1 },
    PAYMENT_CONFLICT: { assembly: 0.4, tone: 'bad', level: 0.85 },
    EXPIRED: { assembly: 0.4, tone: 'bad', level: 0.7 },
  };
  function inside(polygon, x, y) {
    let hit = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [xi, yi] = polygon[i];
      const [xj, yj] = polygon[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }
  function shieldPoints(step, random) {
    const points = [];
    const depth = 0.075;
    const add = (x, y, z, nx, ny, nz) => points.push({ x, y, z, nx, ny, nz, ox: random() - 0.5, oy: random() - 0.5, oz: random() - 0.5, phase: random() * 6.283 });
    const inner = outline.map(([x, y]) => [x * 0.68, y * 0.68 - 0.04]);
    for (let y = -0.55; y <= 0.55; y += step) {
      for (let x = -0.5; x <= 0.5; x += step) {
        if (!inside(outline, x, y)) continue;
        if (inside(inner, x, y)) add(x, y, depth, 0, 0, 1);
        else {
          // The raised rim leans outward so it catches light differently from the face.
          const length = Math.hypot(x, y + 0.04) || 1;
          add(x, y, depth + 0.03, (x / length) * 0.55, ((y + 0.04) / length) * 0.55, 0.83);
        }
        add(x, y, -depth, 0, 0, -1);
      }
    }
    outline.forEach(([ax, ay], index) => {
      const [bx, by] = outline[(index + 1) % outline.length];
      const length = Math.hypot(bx - ax, by - ay);
      for (let t = 0; t <= length; t += step) {
        for (let z = -depth; z <= depth + 0.03; z += step) add(ax + ((bx - ax) * t) / length, ay + ((by - ay) * t) / length, z, (by - ay) / length, -(bx - ax) / length, 0);
      }
    });
    return points;
  }
  function shieldScene(canvas) {
    const cell = 5;
    let points = [];
    let pointsKey = '';
    let assembly = shieldStates.idle.assembly;
    const scene = {
      canvas,
      state: shieldStates.idle,
      draw(time, delta) {
        const { ctx, width, height } = fit(canvas);
        if (!width || !height) return;
        const size = Math.min(width, height);
        const scale = size * 0.56;
        const key = `${Math.round(scale)}`;
        if (key !== pointsKey) {
          pointsKey = key;
          points = shieldPoints(Math.max((cell / scale) * 0.7, 0.008), generator(5));
        }
        const target = scene.state.assembly;
        assembly = delta ? assembly + (target - assembly) * (1 - Math.exp(-delta * 2.4)) : target;
        const still = reducedMotion.matches;
        const yaw = still ? 0.42 : Math.sin(time * 0.42) * 0.62;
        const pitch = still ? -0.14 : -0.14 + Math.sin(time * 0.31) * 0.05;
        const [cy, sy, cp, sp] = [Math.cos(yaw), Math.sin(yaw), Math.cos(pitch), Math.sin(pitch)];
        const light = [-0.42, -0.5, 0.76];
        const spread = (1 - assembly) * 1.1;
        const columns = Math.ceil(width / cell);
        const rows = Math.ceil(height / cell);
        const depthBuffer = new Float32Array(columns * rows).fill(-Infinity);
        const shade = new Float32Array(columns * rows);
        const camera = 3.2;
        const centerX = width / 2;
        const centerY = height * 0.5;
        for (const p of points) {
          const drift = still ? 0 : Math.sin(time * 0.8 + p.phase) * 0.04;
          const x = p.x + (p.ox + drift) * spread;
          const y = p.y + (p.oy - drift) * spread;
          const z = p.z + p.oz * spread;
          const x1 = x * cy + z * sy;
          const z1 = -x * sy + z * cy;
          const y2 = y * cp - z1 * sp;
          const z2 = y * sp + z1 * cp;
          const perspective = camera / (camera - z2);
          const column = Math.floor((centerX + x1 * scale * perspective) / cell);
          const row = Math.floor((centerY + y2 * scale * perspective) / cell);
          if (column < 0 || row < 0 || column >= columns || row >= rows) continue;
          const index = row * columns + column;
          if (z2 <= depthBuffer[index]) continue;
          depthBuffer[index] = z2;
          const nx = p.nx * cy + p.nz * sy;
          const nz1 = -p.nx * sy + p.nz * cy;
          const ny = p.ny * cp - nz1 * sp;
          const nz = p.ny * sp + nz1 * cp;
          shade[index] = 0.22 + 0.78 * Math.max(0, nx * light[0] + ny * light[1] + nz * light[2]);
        }
        ctx.fillStyle = colors[scene.state.tone] || colors.ink;
        for (let row = 0; row < rows; row++) {
          for (let column = 0; column < columns; column++) {
            const index = row * columns + column;
            if (depthBuffer[index] === -Infinity) continue;
            const brightness = shade[index] * scene.state.level;
            if (brightness * 16 <= bayer[(row & 3) * 4 + (column & 3)] * 0.85) continue;
            ctx.globalAlpha = 0.35 + 0.65 * brightness;
            ctx.fillRect(column * cell, row * cell, cell - 2, cell - 2);
          }
        }
        ctx.globalAlpha = 1;
      },
    };
    return scene;
  }

  function loop(now) {
    frame = 0;
    const delta = last ? Math.min((now - last) / 1000, 0.05) : 0;
    last = now;
    for (const scene of scenes) if (scene.visible) scene.draw(now / 1000, delta);
    schedule();
  }
  function schedule() {
    if (frame) return;
    if (reducedMotion.matches || document.hidden || !scenes.some((scene) => scene.visible)) {
      last = 0;
      return;
    }
    frame = requestAnimationFrame(loop);
  }
  function refresh() {
    readColors();
    if (reducedMotion.matches) for (const scene of scenes) if (scene.visible) scene.draw(0, 0);
    schedule();
  }

  const boundaryCanvas = document.getElementById('boundary-canvas');
  const shieldCanvas = document.getElementById('shield-canvas');
  const shield = shieldCanvas ? shieldScene(shieldCanvas) : null;
  if (boundaryCanvas) scenes.push(boundaryScene(boundaryCanvas));
  if (shield) scenes.push(shield);
  const visibility = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const scene = scenes.find((candidate) => candidate.canvas === entry.target);
      if (scene) scene.visible = entry.isIntersecting;
    }
    refresh();
  });
  const resize = new ResizeObserver(() => { if (reducedMotion.matches) refresh(); });
  for (const scene of scenes) {
    visibility.observe(scene.canvas);
    resize.observe(scene.canvas);
  }
  document.addEventListener('visibilitychange', schedule);
  reducedMotion.addEventListener('change', refresh);
  readColors();

  window.pegasusVisuals = {
    setZone(name) {
      document.body.dataset.zone = name;
      refresh();
    },
    setShield(status) {
      if (!shield) return;
      shield.state = shieldStates[status] || shieldStates.idle;
      refresh();
    },
  };
})();

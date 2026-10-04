/* Dark surfaces need a light wordmark, but CSS invert turns Stella's red letter cyan.
   Process each source once when it changes; the small red halo is baked into the image. */
(function () {
  const cache = new Map();

  function forDark(source, options = {}) {
    if (!source) return Promise.resolve(source);
    const crop = !!options.crop;
    const glow = !!options.glow;
    const key = `${crop}:${glow}:${source}`;
    if (cache.has(key)) return cache.get(key);

    const result = new Promise(resolve => {
      const image = new Image();
      image.onload = () => {
        try {
          const scale = Math.min(1, 1024 / Math.max(image.naturalWidth, image.naturalHeight));
          const canvas = document.createElement('canvas');
          canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
          canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
          const context = canvas.getContext('2d', { willReadFrequently: true });
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
          const data = pixels.data;
          const redPixels = glow ? context.createImageData(canvas.width, canvas.height) : null;
          let left = canvas.width, top = canvas.height, right = -1, bottom = -1;
          let hasRed = false;

          for (let y = 0; y < canvas.height; y++) {
            for (let x = 0; x < canvas.width; x++) {
              const offset = (y * canvas.width + x) * 4;
              const alpha = data[offset + 3];
              if (alpha < 20) continue;
              left = Math.min(left, x); top = Math.min(top, y);
              right = Math.max(right, x); bottom = Math.max(bottom, y);
              const red = data[offset], green = data[offset + 1], blue = data[offset + 2];
              const isRed = red > green + 8 && red > blue + 8 && red >= 36;
              if (isRed) {
                data[offset] = Math.max(red, 242);
                data[offset + 1] = Math.max(green, 70);
                data[offset + 2] = Math.max(blue, 66);
                if (redPixels) {
                  redPixels.data[offset] = 255;
                  redPixels.data[offset + 1] = 78;
                  redPixels.data[offset + 2] = 72;
                  redPixels.data[offset + 3] = Math.round(alpha * .2);
                  hasRed = true;
                }
              } else if (Math.max(red, green, blue) - Math.min(red, green, blue) < 45
                  && Math.max(red, green, blue) < 210) {
                data[offset] = 246;
                data[offset + 1] = 248;
                data[offset + 2] = 251;
              }
            }
          }
          if (right < left || bottom < top) return resolve(source);
          context.putImageData(pixels, 0, 0);
          const output = document.createElement('canvas');
          output.width = crop ? right - left + 1 : canvas.width;
          output.height = crop ? bottom - top + 1 : canvas.height;
          const outputContext = output.getContext('2d');
          if (hasRed) {
            const mask = document.createElement('canvas');
            mask.width = canvas.width;
            mask.height = canvas.height;
            mask.getContext('2d').putImageData(redPixels, 0, 0);
            outputContext.shadowColor = 'rgba(255, 82, 76, .32)';
            outputContext.shadowBlur = Math.max(4, Math.round(output.width * .035));
            outputContext.drawImage(mask, crop ? left : 0, crop ? top : 0,
              output.width, output.height, 0, 0, output.width, output.height);
            outputContext.shadowBlur = 0;
          }
          outputContext.drawImage(canvas, crop ? left : 0, crop ? top : 0,
            output.width, output.height, 0, 0, output.width, output.height);
          resolve(output.toDataURL('image/png'));
        } catch (error) {
          resolve(source);
        }
      };
      image.onerror = () => resolve(source);
      image.src = source;
    });
    cache.set(key, result);
    if (cache.size > 4) cache.delete(cache.keys().next().value);
    return result;
  }

  window.StellaBrandLogo = { forDark };
})();

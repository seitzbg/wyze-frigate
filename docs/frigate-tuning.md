# Frigate tuning for Wyze cameras

These settings came from six Bulb Cams recording around a house. Treat the
numbers as starting points and check them with your own cameras.

## Detect at the stream's own resolution

Set `detect.width` and `detect.height` per camera to what `measure-stream`
reports. Frigate saves snapshots from the detect frame, so a lower detect
resolution means smaller stills in Explore. Recordings keep the full
resolution either way. Setting the size explicitly also skips the
per-camera probe Frigate otherwise runs at startup.

## Foliage

Leaves moving in the wind count as motion and start detection over and over.
On five cameras with trees in view, the default `contour_area` (10) kept
detection running at 15-19 fps on a 5 fps stream and about 30% CPU per
camera. Raising it to 30 brought that down to 1-4 fps and 3-9% CPU:

```yaml
cameras:
  back_yard:
    motion:
      contour_area: 30
```

Leave cameras without foliage at the default. Fine-tune in Frigate's motion
tuner (Settings) and copy the values back into the config.

## Motion masks

A motion mask stops an area from starting detection. Objects already being
tracked are still followed through it.

- **The burned-in timestamp.** Wyze stamps the time in the lower right
  corner. It changes every second, so a camera with the default
  `contour_area` can see motion around the clock. On a 2304x1296 Bulb Cam
  this mask covers it:

  ```yaml
  motion:
    mask:
      timestamp:
        coordinates: "0.77,0.93,1,0.93,1,1,0.77,1"
  ```

- **Tree tops against the sky.** Mask the canopy above the tree line, not
  the ground where people walk.
- **Machinery.** An AC condenser fan read as motion whenever it ran.

Coordinates are fractions of the frame (x,y pairs). Draw masks in Frigate's
UI and copy the result. Masks cannot help with insects drawn to a camera's
own light at dusk.

On our four cameras that did not face the street, masks cut the share of
recording segments with motion from 85% to 1%, 100% to 6% and 44% to 0%.

## Measuring motion per camera

Frigate's review API merges cameras, so use its database. Open it read-only
so you do not block Frigate's writes:

```sh
sqlite3 'file:config/frigate.db?mode=ro' \
  "select camera, round(avg(motion > 0) * 100) as pct_motion,
          round(avg(objects > 0) * 100) as pct_objects
   from recordings
   where start_time > strftime('%s', 'now', '-1 day')
   group by camera;"
```

A camera with high motion and almost no objects is a masking candidate.

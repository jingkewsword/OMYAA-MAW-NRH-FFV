export function unsupportedVariant(track) {
  return track?.role === 'overlay' && (track.variant ?? 'plain') !== 'plain';
}

export function isTrackEnabled(track, surface) {
  if (surface !== 'preview' && surface !== 'export') throw new Error('Unknown track surface');
  return Boolean(track && track.enabled === true && !unsupportedVariant(track)
    && (surface === 'preview' ? track.preview_visible !== false : track.export?.enabled !== false));
}

export function selectTracks(project, mode = 'main', surface = 'export', { includeOverlay = true } = {}) {
  const tracks = Array.isArray(project?.tracks) ? project.tracks : [];
  const main = tracks.find(track => track?.role === 'main');
  const overlay = tracks.find(track => track?.role === 'overlay');
  const secondary = project?.bilingual?.active_track_id
    ? tracks.find(track => track?.role === 'secondary' && track.id === project.bilingual.active_track_id)
    : tracks.find(track => track?.role === 'secondary');
  const selections = {
    main: [main, ...(includeOverlay ? [overlay] : [])], overlay: [overlay], extension: [secondary],
    main_and_extension: [main, ...(includeOverlay ? [overlay] : []), secondary], all: [main, overlay, secondary],
  };
  if (!Object.hasOwn(selections, mode)) throw new Error('Unknown subtitle track selection');
  return selections[mode].filter(track => isTrackEnabled(track, surface));
}

export const TrackPolicy = Object.freeze({ isTrackEnabled, selectTracks, unsupportedVariant });

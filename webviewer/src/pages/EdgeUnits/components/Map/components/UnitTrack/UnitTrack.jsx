import React, { useMemo } from 'react';
import L from 'leaflet';
import { Polyline, Marker, Tooltip, CircleMarker } from 'react-leaflet';
import { useTheme } from 'styled-components';
import { formatInTimezone } from 'utils';

const TIME_OPTIONS = {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZoneName: 'short'
};

const START_ICON = L.divIcon({
  className: 'eu-track-start',
  iconSize: [9, 9],
  iconAnchor: [4, 4]
});

// t can be null for a decimated point with no matched source row.
export const formatPointTime = (t, timezone) =>
  t ? formatInTimezone(new Date(t), timezone, TIME_OPTIONS) : 'unknown time';

export const filterImagePoints = track => track.filter(point => point.img);

export const filterTrackByTimeRange = (track, timeRange) => {
  if (!timeRange) return track;
  return track.filter(point => {
    if (!point.t) return false;
    const ts = new Date(point.t).getTime();
    return ts >= timeRange.start && ts < timeRange.end;
  });
};

export const UnitTrack = ({
  unit,
  telemetryUnit,
  state,
  isSelected,
  isSatellite,
  showImagePoints,
  timezone,
  selectionTimeRange,
  onSelect
}) => {
  const theme = useTheme();
  const track = filterTrackByTimeRange(telemetryUnit?.track ?? [], selectionTimeRange);
  const first = track[0];
  const last = track[track.length - 1];

  const pinIcon = useMemo(() => {
    if (!last) return null;
    const className = [
      'eu-track-pin',
      isSatellite && 'eu-track-pin--satellite',
      state === 'live' && 'eu-track-pin--live'
    ]
      .filter(Boolean)
      .join(' ');
    return L.divIcon({
      className,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      html: `<span class="eu-track-pin-dot" style="background:${theme.colors.status[state]}"></span>`
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, isSatellite, last?.lat, last?.lng]);

  if (!last) return null;

  const casingOptions = {
    color: '#000',
    weight: isSelected ? 5 : 3.5,
    opacity: isSatellite ? 0.4 : 0.18
  };
  const coreOptions = {
    color: isSatellite
      ? isSelected
        ? theme.colors.nature.n0
        : theme.colors.nature.n2
      : isSelected
      ? theme.colors.nature.n5
      : theme.colors.nature.n3,
    weight: isSelected ? 2.2 : 1.4,
    opacity: isSelected ? 0.95 : isSatellite ? 0.6 : 0.45
  };

  return (
    <>
      {track.length > 1 && (
        <>
          <Polyline
            positions={track.map(point => [point.lat, point.lng])}
            pathOptions={casingOptions}
          />
          <Polyline
            positions={track.map(point => [point.lat, point.lng])}
            pathOptions={coreOptions}
          />
          <Marker position={[first.lat, first.lng]} icon={START_ICON}>
            <Tooltip direction='top'>
              Started {formatPointTime(first.t, timezone)}
            </Tooltip>
          </Marker>
        </>
      )}

      <Marker
        position={[last.lat, last.lng]}
        icon={pinIcon}
        eventHandlers={{ click: () => onSelect(unit.unit_id) }}
      >
        <Tooltip direction='top' offset={[0, -10]}>
          <b>{unit.unit_id}</b>
          <br />
          {unit.machine_label}
          <br />
          {formatPointTime(last.t, timezone)}
        </Tooltip>
      </Marker>

      {showImagePoints &&
        filterImagePoints(track).map((point, index) => (
          <CircleMarker
            key={index}
            center={[point.lat, point.lng]}
            radius={3}
            pathOptions={{
              fillColor: theme.colors.status.late,
              fillOpacity: 0.95,
              color: theme.colors.nature.n5,
              weight: 1,
              opacity: 0.55
            }}
          >
            <Tooltip direction='top'>Image {formatPointTime(point.t, timezone)}</Tooltip>
          </CircleMarker>
        ))}
    </>
  );
};

import React, { useState } from 'react';
import { formatInTimezone } from 'utils';
import { Button } from 'components/_shared/Button';
import { STATE_LABELS } from '../../constants';
import {
  Column,
  Heading,
  Tiles,
  Tile,
  TileLabel,
  TileValue,
  AlertList,
  AlertItem,
  ActivityLog,
  ActivityItem,
  ActivityTime,
  EmptyMessage,
  ImageFrame,
  ImagePlaceholder,
  Caption,
  ImageRetryRow
} from './DetailPanel.styles';

const DASH = '—';
const ACTIVITY_LOG_SIZE = 6;

const TIME_OPTIONS = {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZoneName: 'short'
};

const SEVERITY_TO_STATE = {
  ok: 'live',
  medium: 'late',
  high: 'silent'
};

export const cameraTileValue = (alerts, totals) => {
  if (!totals?.messages) return { value: 'No data', warn: false };
  const noImages = (alerts ?? []).some(alert => alert.rule === 'no_images');
  return { value: noImages ? 'No images' : 'Working', warn: noImages };
};

export const lastMessageValue = (totals, timezone) =>
  totals?.messages > 0
    ? formatInTimezone(new Date(totals.last_at), timezone, TIME_OPTIONS)
    : DASH;

export const latestImageCaption = (capturedAt, timezone) =>
  capturedAt ? formatInTimezone(new Date(capturedAt), timezone, TIME_OPTIONS) : DASH;

export const activityLogEntries = (track, timezone) =>
  (track ?? [])
    .slice(-ACTIVITY_LOG_SIZE)
    .reverse()
    .map(point => ({
      key: point.t,
      time: formatInTimezone(new Date(point.t), timezone, TIME_OPTIONS),
      text:
        'Position' +
        (point.img ? ' + image' : '') +
        (point.det ? ` · ${point.det} stone${point.det > 1 ? 's' : ''} detected` : '')
    }));

export const DetailPanel = ({
  unit,
  telemetryUnit,
  activityTrack,
  state,
  timezone,
  latestImage,
  isLatestImageLoading,
  latestImageError,
  onRetryLatestImage
}) => {
  const [retriedUrl, setRetriedUrl] = useState(null);

  if (!unit) {
    return <EmptyMessage>No unit selected.</EmptyMessage>;
  }

  const alerts = telemetryUnit?.alerts ?? [];
  const camera = cameraTileValue(alerts, telemetryUnit?.totals);
  const entries = activityLogEntries(activityTrack, timezone);

  const handleImageError = () => {
    if (retriedUrl === latestImage.url) return;
    setRetriedUrl(latestImage.url);
    onRetryLatestImage();
  };

  return (
    <>
      <Column>
        <Tiles>
          <Tile $state={state}>
            <TileLabel>Status</TileLabel>
            <TileValue>{STATE_LABELS[state] ?? DASH}</TileValue>
          </Tile>
          <Tile $warn={camera.warn}>
            <TileLabel>Camera</TileLabel>
            <TileValue>{camera.value}</TileValue>
          </Tile>
          <Tile>
            <TileLabel>Last message</TileLabel>
            <TileValue>{lastMessageValue(telemetryUnit?.totals, timezone)}</TileValue>
          </Tile>
        </Tiles>
        <Heading>Recent activity</Heading>
        <ActivityLog>
          {entries.length > 0 ? (
            entries.map(entry => (
              <ActivityItem key={entry.key}>
                <ActivityTime>{entry.time}</ActivityTime>
                <span>{entry.text}</span>
              </ActivityItem>
            ))
          ) : (
            <EmptyMessage>Nothing recorded in this window.</EmptyMessage>
          )}
        </ActivityLog>
      </Column>
      <Column>
        <Heading>Needs attention</Heading>
        <AlertList>
          {alerts.map(alert => (
            <AlertItem
              key={alert.rule}
              $severity={SEVERITY_TO_STATE[alert.severity] ?? 'live'}
            >
              {alert.copy}
            </AlertItem>
          ))}
        </AlertList>
        <Heading>Latest image</Heading>
        {isLatestImageLoading ? (
          <ImagePlaceholder>Loading…</ImagePlaceholder>
        ) : latestImage?.url ? (
          <>
            <ImageFrame>
              <img
                src={latestImage.url}
                alt={`${unit.unit_id} latest capture`}
                onError={handleImageError}
              />
            </ImageFrame>
            <Caption>{latestImageCaption(latestImage.captured_at, timezone)}</Caption>
          </>
        ) : latestImageError ? (
          <ImageRetryRow>
            <span>{latestImageError.data}</span>
            <Button onClick={onRetryLatestImage}>Retry</Button>
          </ImageRetryRow>
        ) : null}
      </Column>
    </>
  );
};

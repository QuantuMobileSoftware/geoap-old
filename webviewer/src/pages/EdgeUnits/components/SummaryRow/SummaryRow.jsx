import React from 'react';
import { formatInTimezone } from 'utils';
import { Row, Stat, StatLabel, StatValue } from './SummaryRow.styles';

const DASH = '—';

const TIME_OPTIONS = {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZoneName: 'short'
};

const STATS = [
  ['messages', 'Messages received'],
  ['distance', 'Distance covered'],
  ['firstMessage', 'First message'],
  ['lastMessage', 'Last message'],
  ['images', 'Images uploaded'],
  ['detections', 'Stones detected'],
  ['quietTime', 'Quiet periods']
];

// messages === 0 means no data - dash every field, not just "0" ones.
export const summaryFields = (totals, timezone) => {
  const hasData = Boolean(totals && totals.messages > 0);

  if (!hasData) {
    return {
      messages: DASH,
      distance: DASH,
      firstMessage: DASH,
      lastMessage: DASH,
      images: DASH,
      detections: DASH,
      quietTime: DASH
    };
  }

  const formatTime = t =>
    t ? formatInTimezone(new Date(t), timezone, TIME_OPTIONS) : DASH;

  return {
    messages: totals.messages.toLocaleString(),
    distance: `${totals.distance_km.toFixed(1)} km`,
    firstMessage: formatTime(totals.first_at),
    lastMessage: formatTime(totals.last_at),
    images: totals.images.toLocaleString(),
    detections: totals.detections.toLocaleString(),
    quietTime: totals.gap_minutes > 0 ? `${totals.gap_minutes} min` : 'none'
  };
};

export const SummaryRow = ({ totals, timezone }) => {
  const fields = summaryFields(totals, timezone);

  return (
    <Row>
      {STATS.map(([key, label]) => (
        <Stat key={key}>
          <StatLabel>{label}</StatLabel>
          <StatValue>{fields[key]}</StatValue>
        </Stat>
      ))}
    </Row>
  );
};

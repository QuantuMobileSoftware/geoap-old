import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThemeProvider } from 'styled-components';
import { themeDefault } from 'styles/themes/theme.default';
import {
  cameraTileValue,
  lastMessageValue,
  latestImageCaption,
  activityLogEntries,
  DetailPanel
} from './DetailPanel';

jest.mock('lodash-es', () => require('lodash'));

const timezone = 'America/Regina';

const alert = (rule, severity = 'high', copy = rule) => ({ rule, severity, copy });

const point = (t, overrides = {}) => ({
  t,
  lat: 50,
  lng: -98,
  img: false,
  det: 0,
  ...overrides
});

const withTheme = children => (
  <ThemeProvider theme={themeDefault}>{children}</ThemeProvider>
);

describe('cameraTileValue', () => {
  it('is "No images" and warns when the no_images alert is present', () => {
    expect(cameraTileValue([alert('no_images'), alert('late', 'medium')])).toEqual({
      value: 'No images',
      warn: true
    });
  });

  it('is "Working" when no_images is absent', () => {
    expect(cameraTileValue([alert('ok', 'ok')])).toEqual({
      value: 'Working',
      warn: false
    });
  });

  it('is "Working" when there are no alerts at all', () => {
    expect(cameraTileValue(undefined)).toEqual({ value: 'Working', warn: false });
  });
});

describe('lastMessageValue', () => {
  it('formats totals.last_at in the account timezone', () => {
    const totals = { messages: 3, last_at: '2026-08-26T13:30:00Z' };
    expect(lastMessageValue(totals, timezone)).toBe('07:30 CST');
  });

  it('dashes when there are zero messages in the window', () => {
    expect(
      lastMessageValue({ messages: 0, last_at: '2026-08-26T13:30:00Z' }, timezone)
    ).toBe('—');
  });

  it('dashes when totals is missing entirely', () => {
    expect(lastMessageValue(undefined, timezone)).toBe('—');
  });
});

describe('latestImageCaption', () => {
  it('formats captured_at in the account timezone', () => {
    expect(latestImageCaption('2026-08-26T13:30:00Z', timezone)).toBe('07:30 CST');
  });

  it('dashes when there is no captured_at', () => {
    expect(latestImageCaption(undefined, timezone)).toBe('—');
  });
});

describe('activityLogEntries', () => {
  it('returns the last 6 points, newest first', () => {
    const track = Array.from({ length: 8 }, (_, i) =>
      point(`2026-08-26T12:0${i}:00Z`, { img: false, det: 0 })
    );

    const entries = activityLogEntries(track, timezone);

    expect(entries).toHaveLength(6);
    expect(entries[0].key).toBe('2026-08-26T12:07:00Z');
    expect(entries[5].key).toBe('2026-08-26T12:02:00Z');
  });

  it('formats image and detection combinations', () => {
    const track = [
      point('2026-08-26T12:00:00Z', { img: false, det: 0 }),
      point('2026-08-26T12:01:00Z', { img: true, det: 0 }),
      point('2026-08-26T12:02:00Z', { img: false, det: 1 }),
      point('2026-08-26T12:03:00Z', { img: true, det: 3 })
    ];

    const entries = activityLogEntries(track, timezone).map(entry => entry.text);

    expect(entries).toEqual([
      'Position + image · 3 stones detected',
      'Position · 1 stone detected',
      'Position + image',
      'Position'
    ]);
  });

  it('returns an empty list when there is no track data', () => {
    expect(activityLogEntries(undefined, timezone)).toEqual([]);
    expect(activityLogEntries([], timezone)).toEqual([]);
  });
});

describe('DetailPanel render', () => {
  const unit = { unit_id: 'SS-0142', machine_label: 'Case 8250 combine' };

  it('shows an empty message when no unit is selected', () => {
    render(withTheme(<DetailPanel unit={null} />));
    expect(screen.getByText('No unit selected.')).toBeInTheDocument();
  });

  it('renders the health tiles, needs-attention list and activity log', () => {
    const telemetryUnit = {
      alerts: [
        alert('late', 'medium', "This unit's last message came in later than usual.")
      ],
      totals: { messages: 2, last_at: '2026-08-26T13:30:00Z' }
    };
    const activityTrack = [point('2026-08-26T12:00:00Z', { img: true, det: 2 })];

    render(
      withTheme(
        <DetailPanel
          unit={unit}
          telemetryUnit={telemetryUnit}
          activityTrack={activityTrack}
          state='late'
          timezone={timezone}
        />
      )
    );

    expect(screen.getByText('Late')).toBeInTheDocument();
    expect(screen.getByText('Working')).toBeInTheDocument();
    expect(screen.getByText('07:30 CST')).toBeInTheDocument();
    expect(
      screen.getByText("This unit's last message came in later than usual.")
    ).toBeInTheDocument();
    expect(screen.getByText('Position + image · 2 stones detected')).toBeInTheDocument();
  });

  it('shows the all-clear alert when nothing fires', () => {
    render(
      withTheme(
        <DetailPanel
          unit={unit}
          telemetryUnit={{
            alerts: [alert('ok', 'ok', 'Everything looks normal for this unit.')]
          }}
          state='live'
          timezone={timezone}
        />
      )
    );

    expect(
      screen.getByText('Everything looks normal for this unit.')
    ).toBeInTheDocument();
  });

  it('renders every co-fired alert in the order the backend returns them', () => {
    const rules = ['late', 'no_images', 'no_gps_fix', 'detection_not_running'];
    const telemetryUnit = { alerts: rules.map(rule => alert(rule, 'high', rule)) };

    render(
      withTheme(
        <DetailPanel
          unit={unit}
          telemetryUnit={telemetryUnit}
          state='late'
          timezone={timezone}
        />
      )
    );

    const rendered = screen.getAllByRole('listitem').map(item => item.textContent);
    rules.forEach(rule => expect(rendered).toContain(rule));
  });

  it('never renders Storage, Power or a staff block, under any props', () => {
    const telemetryUnit = {
      alerts: [alert('ok', 'ok', 'Everything looks normal for this unit.')],
      totals: { messages: 5, last_at: '2026-08-26T13:30:00Z' }
    };

    render(
      withTheme(
        <DetailPanel
          unit={unit}
          telemetryUnit={telemetryUnit}
          activityTrack={[point('2026-08-26T12:00:00Z')]}
          state='live'
          timezone={timezone}
        />
      )
    );

    expect(screen.queryByText(/storage/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/power/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/staff|internal/i)).not.toBeInTheDocument();
  });

  it('narrows the activity log on a track prop swap without touching tiles or alerts', () => {
    const telemetryUnit = {
      alerts: [alert('ok', 'ok', 'Everything looks normal for this unit.')],
      totals: { messages: 5, last_at: '2026-08-26T13:30:00Z' }
    };
    const fullTrack = [
      point('2026-08-26T12:00:00Z', { det: 1 }),
      point('2026-08-26T12:05:00Z', { det: 2 })
    ];
    const narrowedTrack = [point('2026-08-26T12:05:00Z', { det: 2 })];

    const { rerender } = render(
      withTheme(
        <DetailPanel
          unit={unit}
          telemetryUnit={telemetryUnit}
          activityTrack={fullTrack}
          state='live'
          timezone={timezone}
        />
      )
    );
    expect(screen.getByText('Position · 1 stone detected')).toBeInTheDocument();

    rerender(
      withTheme(
        <DetailPanel
          unit={unit}
          telemetryUnit={telemetryUnit}
          activityTrack={narrowedTrack}
          state='live'
          timezone={timezone}
        />
      )
    );

    expect(screen.queryByText('Position · 1 stone detected')).not.toBeInTheDocument();
    expect(
      screen.getByText('Everything looks normal for this unit.')
    ).toBeInTheDocument();
  });

  describe('latest image', () => {
    const telemetryUnit = {
      alerts: [alert('ok', 'ok', 'Everything looks normal for this unit.')]
    };

    it('shows a loading placeholder and no image', () => {
      render(
        withTheme(
          <DetailPanel
            unit={unit}
            telemetryUnit={telemetryUnit}
            state='live'
            timezone={timezone}
            isLatestImageLoading
          />
        )
      );

      expect(screen.getByText('Loading…')).toBeInTheDocument();
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
    });

    it('renders the image with its capture-time caption', () => {
      render(
        withTheme(
          <DetailPanel
            unit={unit}
            telemetryUnit={telemetryUnit}
            state='live'
            timezone={timezone}
            latestImage={{
              url: 'https://example.com/img.jpg',
              captured_at: '2026-08-26T13:30:00Z'
            }}
          />
        )
      );

      expect(screen.getByRole('img')).toHaveAttribute(
        'src',
        'https://example.com/img.jpg'
      );
      expect(screen.getByText('07:30 CST')).toBeInTheDocument();
    });

    it('shows the backend error message and a working Retry button', () => {
      const onRetryLatestImage = jest.fn();

      render(
        withTheme(
          <DetailPanel
            unit={unit}
            telemetryUnit={telemetryUnit}
            state='live'
            timezone={timezone}
            latestImageError={{
              status: 'CUSTOM_ERROR',
              data: 'No image has been received for this unit yet.'
            }}
            onRetryLatestImage={onRetryLatestImage}
          />
        )
      );

      expect(
        screen.getByText('No image has been received for this unit yet.')
      ).toBeInTheDocument();
      fireEvent.click(screen.getByText('Retry'));
      expect(onRetryLatestImage).toHaveBeenCalledTimes(1);
    });

    it('retries at most once per broken image URL', () => {
      const onRetryLatestImage = jest.fn();

      render(
        withTheme(
          <DetailPanel
            unit={unit}
            telemetryUnit={telemetryUnit}
            state='live'
            timezone={timezone}
            latestImage={{ url: 'https://example.com/img.jpg', captured_at: null }}
            onRetryLatestImage={onRetryLatestImage}
          />
        )
      );

      const img = screen.getByRole('img');
      fireEvent.error(img);
      fireEvent.error(img);
      fireEvent.error(img);

      expect(onRetryLatestImage).toHaveBeenCalledTimes(1);
    });
  });
});

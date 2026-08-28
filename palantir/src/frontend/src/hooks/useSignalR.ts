import { useEffect, useRef } from 'react';
import { HubConnectionBuilder, LogLevel, HubConnection } from '@microsoft/signalr';
import { useQueryClient } from '@tanstack/react-query';

/**
 * Connects to the AEGIS SignalR hub and invalidates React Query caches
 * when new events or risk cases arrive, causing automatic UI refresh.
 */
export function useSignalR() {
  const queryClient = useQueryClient();
  const connectionRef = useRef<HubConnection | null>(null);

  useEffect(() => {
    const connection = new HubConnectionBuilder()
      .withUrl('/hub/alerts')
      .withAutomaticReconnect([0, 2000, 5000, 10000, 30000])
      .configureLogging(LogLevel.Information)
      .build();

    connectionRef.current = connection;

    // When a new event is ingested → refresh events, dashboard, timeline
    connection.on('NewEvent', (_alert) => {
      queryClient.invalidateQueries({ queryKey: ['events'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      queryClient.invalidateQueries({ queryKey: ['timeline'] });
    });

    // When a new risk case is created by the inference engine → refresh cases + dashboard
    connection.on('NewRiskCase', (_alert) => {
      queryClient.invalidateQueries({ queryKey: ['risk-cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    });

    // Critical alert → also refresh
    connection.on('CriticalAlert', (_alert) => {
      queryClient.invalidateQueries({ queryKey: ['events'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    });

    connection.on('Connected', (info) => {
      console.log('🛰️ Connected to AEGIS real-time hub', info);
    });

    connection
      .start()
      .then(() => console.log('🛰️ SignalR connected'))
      .catch((err) => console.warn('SignalR connection failed:', err));

    return () => {
      connection.stop();
    };
  }, [queryClient]);

  return connectionRef;
}

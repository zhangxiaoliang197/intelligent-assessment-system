import * as signalR from '@microsoft/signalr';
import type { OntologyMutation } from '@/types/dynamicOntology';
export function createOntologyConnection(onMutation:(m:OntologyMutation)=>void){
 const connection=new signalR.HubConnectionBuilder().withUrl('/hub/ontology').withAutomaticReconnect().build();
 connection.on('OntologyMutation',onMutation);
 return connection;
}

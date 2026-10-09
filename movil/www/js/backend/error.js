export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.status = status;
    this.data = data;  // p. ej. {confirmar: {...}} cuando el servidor pide una confirmación (409)
  }
}

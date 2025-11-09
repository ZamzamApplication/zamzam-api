# Zamzam API

A Spring Boot-based REST API for the Zamzam application, providing backend services for user management, organizations, halaqas, and daily progress tracking.

## Features

- **User Authentication**: JWT-based authentication with secure login/logout
- **Organization Management**: Create and manage organizations with membership controls
- **Halaqa System**: Manage study circles (halaqas) with member assignments
- **Progress Tracking**: Record and monitor learning progress
- **RESTful API**: Clean, documented endpoints for all operations

## Tech Stack

- **Framework**: Spring Boot 3.5.6
- **Language**: Java 21
- **Database**: PostgreSQL with JPA/Hibernate
- **Security**: Spring Security with JWT authentication
- **Documentation**: SpringDoc OpenAPI (Swagger UI) (In progress)
- **Build Tool**: Maven

## Quick Start

### Prerequisites

- Java 21 or higher
- Maven 3.6+
- PostgreSQL database

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd zamzam-api
   ```

2. **Configure Database**:
   Update `src/main/resources/application.properties` with your PostgreSQL credentials:
   ```properties
   spring.datasource.url=jdbc:postgresql://localhost:5432/zamzam_db
   spring.datasource.username=your_username
   spring.datasource.password=your_password
   ```

3. **Run with Maven**:
   ```bash
   mvn clean install
   mvn spring-boot:run
   ```

4. **Run with Docker** (alternative):
   ```bash
   docker-compose up --build
   ```

The API will be available at `http://localhost:8080`

## API Documentation

- **Docs Repository**: you can check [docs](https://github.com/zamzamapplication/docs) repository for all documentations.
- **Swagger UI**: Will be Available at `http://localhost:8080/swagger-ui.html` when the API is running

## Project Structure

```
src/main/java/com/zamzam/zamzamapi/
├── config/          # Security, JWT, and configuration classes
├── controller/      # REST API endpoints
├── dto/            # Data Transfer Objects
├── entity/         # JPA entities
├── exception/      # Custom exceptions and handlers
├── repository/     # Data access layer
└── service/        # Business logic layer
```

## Testing

Run tests with:
```bash
mvn test
```

## Contributing

See the main project documentation for contribution guidelines.

## Documentation

For detailed project documentation, API specifications, data models, and more, visit the [docs](https://github.com/zamzamapplication/docs) repository.

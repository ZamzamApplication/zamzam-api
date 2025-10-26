import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

public class HashPassword {
    public static void main(String[] args) {
        BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
        String password = "password123"; // Change this to your desired password
        String hashed = encoder.encode(password);
        System.out.println("Password: " + password);
        System.out.println("Hashed: " + hashed);
    }
}
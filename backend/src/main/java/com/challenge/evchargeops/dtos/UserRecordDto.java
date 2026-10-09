package com.challenge.evchargeops.dtos;

import com.fasterxml.jackson.annotation.JsonView;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record UserRecordDto(@NotBlank(groups = UserView.RegistrationPost.class, message = "Username is mandatory")
                            @Size(min = 4, max = 50, groups = UserView.RegistrationPost.class, message = "Size must be between 4 and 50")
                            @JsonView(UserView.RegistrationPost.class)
                            String username,

                            @NotBlank(groups = UserView.RegistrationPost.class, message = "E-mail is mandatory")
                            @Email(groups = UserView.RegistrationPost.class, message = "E-mail must be in the expected format")
                            @Size(max = 50, groups = UserView.RegistrationPost.class, message = "E-mail must have at most 50 characters")
                            @JsonView(UserView.RegistrationPost.class)
                            String email,

                            @NotBlank(groups = {UserView.RegistrationPost.class, UserView.PasswordPut.class}, message = "Password is mandatory")
                            @Size(min = 6, max = 20, groups = {UserView.RegistrationPost.class, UserView.PasswordPut.class},  message = "Size must be between 6 and 20")
                            @JsonView({UserView.RegistrationPost.class, UserView.PasswordPut.class})
                            String password,

                            @NotBlank(groups = UserView.PasswordPut.class, message = "Old password is mandatory")
                            @Size(min = 6, max = 20, groups = UserView.PasswordPut.class, message = "Size must be between 6 and 20")
                            @JsonView(UserView.PasswordPut.class)
                            String oldPassword,

                            @Size(max = 150, groups = {UserView.RegistrationPost.class, UserView.UserPut.class}, message = "Full name must have at most 150 characters")
                            @JsonView({UserView.RegistrationPost.class, UserView.UserPut.class})
                            String fullName,

                            @Size(max = 20, groups = {UserView.RegistrationPost.class, UserView.UserPut.class}, message = "Phone number must have at most 20 characters")
                            @JsonView({UserView.RegistrationPost.class, UserView.UserPut.class})
                            String phoneNumber) {

    public interface UserView {
        interface RegistrationPost {}
        interface UserPut {}
        interface PasswordPut {}
    }
}

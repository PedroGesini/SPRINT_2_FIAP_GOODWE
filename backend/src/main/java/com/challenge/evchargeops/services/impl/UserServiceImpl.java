package com.challenge.evchargeops.services.impl;

import com.challenge.evchargeops.dtos.UserRecordDto;
import com.challenge.evchargeops.enums.UserStatus;
import com.challenge.evchargeops.enums.UserType;
import com.challenge.evchargeops.exceptions.MismatchedOldPasswordException;
import com.challenge.evchargeops.exceptions.NotFoundException;
import com.challenge.evchargeops.exceptions.UserConflictException;
import com.challenge.evchargeops.models.UserModel;
import com.challenge.evchargeops.repositories.UserRepository;
import com.challenge.evchargeops.services.UserService;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RequestBody;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Service
public class UserServiceImpl implements UserService {

    final UserRepository userRepository;

    public UserServiceImpl(UserRepository userRepository) { this.userRepository = userRepository; }


    @Override
    public List<UserModel> findAll() {
        return userRepository.findAll();
    }

    @Override
    public Optional<UserModel> findById(UUID userId) {
        Optional<UserModel> userModelOptional = userRepository.findById(userId);
        if (userModelOptional.isEmpty()) {
            throw new NotFoundException("Error: User not found");
        }
        return userModelOptional;
    }

    @Override
    public void deleteUser(UserModel userModel) {
        userRepository.delete(userModel);
    }

    @Override
    public UserModel registerUser(@RequestBody UserRecordDto userRecordDto) {
        if (userRepository.existsByUsername(userRecordDto.username())) {
            throw new UserConflictException("Error: Username is already taken");
        }
        if (userRepository.existsByEmail(userRecordDto.email())) {
            throw new UserConflictException("Error: Email is already taken");
        }
        var userModel = new UserModel();
        BeanUtils.copyProperties(userRecordDto, userModel);
        userModel.setUserStatus(UserStatus.ACTIVE);
        userModel.setUserType(UserType.USER);
        userModel.setCreationDate(LocalDateTime.now(ZoneId.of("UTC")));
        userModel.setLastUpdateDate(LocalDateTime.now(ZoneId.of("UTC")));

        return userRepository.save(userModel);
    }

    @Override
    public boolean existsByUsername(String username) {
        return userRepository.existsByUsername(username);
    }

    @Override
    public boolean existsByEmail(String email) {
        return userRepository.existsByEmail(email);
    }

    @Override
    public UserModel updateUser(UserRecordDto userRecordDto, UserModel userModel) {
        userModel.setFullName(userRecordDto.fullName());
        userModel.setPhoneNumber(userRecordDto.phoneNumber());
        userModel.setLastUpdateDate(LocalDateTime.now(ZoneId.of("UTC")));
        return userRepository.save(userModel);
    }

    @Override
    public UserModel updatePassword(UserRecordDto userRecordDto, UserModel userModel) {
        if(!userModel.getPassword().equals(userRecordDto.oldPassword())) {
            throw new MismatchedOldPasswordException("Error: Mismatched old password");
        }
        userModel.setPassword(userRecordDto.password());
        userModel.setLastUpdateDate(LocalDateTime.now(ZoneId.of("UTC")));
        return userRepository.save(userModel);
    }
}

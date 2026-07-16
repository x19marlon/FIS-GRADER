package com.skillstack.devhub.builder;

import com.skillstack.devhub.model.Progress;
import com.skillstack.devhub.service.StatisticsService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Scope;
import org.springframework.stereotype.Service;

@Service
public class ProgressBuilder implements ProgressBuilderInterface{
    private final StatisticsService statisticsService;
    private String userId;
    private Progress progress;

    @Autowired
    public ProgressBuilder(StatisticsService statisticsService) {
        this.statisticsService = statisticsService;
    }

    public void forUser(String userId) {
        this.userId = userId;
        this.progress = new Progress();
    }

    @Override
    public void buildTotal() {
        progress.setTotalAnswered(statisticsService.progress("TotalQuestionAnsweredStatistics", userId));
    }

    @Override
    public void buildPercentage() {
        progress.setPercentage(statisticsService.progress("PercentageQuestionsAnsweredStatistics", userId));
    }

    @Override
    public Progress getResult() {
        return progress;
    }
}